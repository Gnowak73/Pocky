import drms
from drms import ServerConfig
from urllib.request import urlretrieve
from urllib.error import URLError, HTTPError
import os
from sunpy.map import Map
import datetime
from datetime import timedelta

from aiapy.calibrate.util import get_correction_table as get_correction_table
from aiapy.calibrate import normalize_exposure, register, update_pointing, correct_degradation
import time

from sunpy.coordinates import frames
import sunpy

import csv

import astropy
from astropy.coordinates import SkyCoord
import astropy.units as u

import numpy as np

#from torchvision.transforms import Resize
#import torch

import glob

from paramiko import SSHClient
from scp import SCPClient
#import dem_rml

import pytz

import cv2

import wget

import pandas as pd

import json

from dateutil import tz

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
import matplotlib.colors as colors

from paramiko import SSHClient
from scp import SCPClient

import shutil

from matplotlib.animation import FuncAnimation
from PIL import Image

#**********************************************************


def mkdir(a_dir):
    """
    Function creating a folder if it does not exists
    
    Parameters
        ----------
        a_dir: string
            path of the folder to be created    
    """
    
    if(not os.path.exists(a_dir)):
        os.makedirs(a_dir)   
        
#**********************************************************        
        
def configure_jsoc_server():
    """
    Function configuring a JSOC server (to be used for quering AIA data throgh drms)
    
    Returns
        -------
        client: drms client server
    """
    
    server = ServerConfig(name="JSOC",
                          cgi_baseurl="http://jsoc2.stanford.edu/cgi-bin/ajax/",
                          cgi_show_series="show_series",
                          cgi_jsoc_info="jsoc_info",
                          cgi_jsoc_fetch="jsoc_fetch",
                          cgi_check_address="checkAddress.sh",
                          cgi_show_series_wrapper="showextseries",
                          show_series_wrapper_dbhost="hmidb2",
                          http_download_baseurl="http://jsoc2.stanford.edu/",
                          ftp_download_baseurl="ftp://pail.stanford.edu/export/")


    client = drms.Client(server=server,verbose=True)
    
    return client

#**********************************************************

def download_aia_data(wav, t_rec, segments, data_folder, timezone='US/Central', silent=False):
    """
    
    Function for downloading near real time AIA data
    
    
    Parameters
        ----------
        wav: numpy array (integer)
            array containing the wavelength number of the AIA data to be downloaded
            
        t_rec: numpy array (string)
            array containing the recorded time of the AIA data to be downloaded
            
        segments: numpy array (string)
            array containing the path of the AIA data to be downloaded
            
        data_folder: string
            path of the folder where the downloaded AIA data are saved 
            
        timezone: string
            timezone w.r.t. the times are expressed. Default, 'US/Central'
            
        silent: boolean
            if True, no text is printed
    
    Returns
        -------
        aia_maps: list
            list containing the downloaded full-disk AIA maps
        
        full_disk_maps_folder: string
            path of the folder where the full-disk AIA maps are downloaded
        
        error: bool
            True if an error occurred while downloading the data
            
    """
    
    # Create download folder
    full_disk_maps_folder = os.path.join(data_folder, t_rec[0].replace(":", ""))
    mkdir(full_disk_maps_folder)
        
    # Get fits file url
    website_url   = 'https://jsoc1.stanford.edu/'
    
    idx      = np.argsort(wav)
    wav      = wav[idx]
    t_rec    = t_rec[idx]
    segments = segments[idx]
    
    this_datetime_timezone = convert_utc_to_timezone(datetime.datetime.strptime(t_rec[0], '%Y-%m-%dT%H:%M:%SZ'),
                                                     timezone=timezone)
    
    if not silent:
        print("\nStart download AIA data recorded at " + this_datetime_timezone.strftime("%d-%m-%YT%H:%M:%S") + " " + timezone)
    
    aia_maps = []
    
    # Error will be true if it is not possible to download a file
    error = False
    for i in range(len(wav)):
    
        fits_file_url = website_url + segments[i]
       
        # Define fits file name
        filename = os.path.join(full_disk_maps_folder, 'aia_lev1_nrt2_'+ t_rec[i] + '_' + str(wav[i]) +'.fits').replace(":", "")

        # Download fits file
        try:
            urlretrieve(fits_file_url, filename)
        except (HTTPError, URLError):
            error = True
            continue
        
        aia_maps.append(Map(filename))
                
    if not silent:
        print("Download completed!")
    return aia_maps, full_disk_maps_folder, error


#**********************************************************

def calibrate_full_disk_maps(aia_maps):
    """
    
    Function for calibrating (i.e., registering) the downloaded full-disk AIA maps
    
    
    Parameters
        ----------
        aia_maps: list
            list containing the full-disk AIA maps to be calibrated 
    
    Returns
        -------
        calibrated_aia_maps: list
            list containing the calibrated full-disk AIA maps
            
    """
    calibrated_aia_maps = []
    
    for this_map in aia_maps:
        calibrated_aia_maps.append(register(this_map))
        
    return calibrated_aia_maps

#**********************************************************

def extract_submap(aia_map, ar_lon, ar_lat, n_pix = 500):
    """
    
    Function for extracting submap around an active region from AIA map
    
    
    Parameters
        ----------
        aia_map: AIA map structure
            AIA map from which the submap is extracted
            
        ar_lon: float
            longitude of center of the active region (Heliographic Stonyhurst coordinates)
            
        ar_lat: float
            latitude of center of the active region (Heliographic Stonyhurst coordinates)
    
        n_pix: integer
            number of pixels of the submap to be extracted. Default, 500
        
        
    Returns
        -------
        submap: AIA map structure
            submap around active region extracted from the AIA map provided as input
            
    """
    this_coord = SkyCoord(ar_lon*u.deg, ar_lat*u.deg, frame=frames.HeliographicStonyhurst)

    pix_x = aia_map.world_to_pixel(this_coord).x.value
    pix_y = aia_map.world_to_pixel(this_coord).y.value

    top_right   = aia_map.pixel_to_world((pix_x+n_pix//2-1)*u.pix,(pix_y+n_pix//2-1)*u.pix)
    bottom_left = aia_map.pixel_to_world((pix_x-n_pix//2)*u.pix,(pix_y-n_pix//2)*u.pix)
    
    submap = aia_map.submap(bottom_left, top_right=top_right)
    submap = Map(submap.data.astype(np.int16), submap.meta)
    
    return submap

#**********************************************************

def crop_full_disk_maps(aia_maps, ar_lon, ar_lat, arnum, cropped_maps_folder, n_pix=1000, save_submaps=False):
    """
    
    Function for cropping AIA maps around an active region. The submaps are saved as fits files
    
    
    Parameters
        ----------
        aia_maps: list
            list of AIA maps from which the submaps are extracted
            
        ar_lon: float
            longitude coordinate of the center of the active region (Heliographic Stonyhurst coordinates)
            
        ar_lat: float
            latitude coordinate of the center of the active region (Heliographic Stonyhurst coordinates)
            
        arnum: integer
            number of the active region to be extracted
    
        n_pix: integer
            number of pixels of the submap to be extracted. Default, 1000
        
        
    Returns
        -------
        aia_submaps: list
            list of submaps cropped an around active region which are extracted from the AIA map provided as input
            
    """
    aia_submaps = []
    for aia_map in aia_maps:
        aia_submap = extract_submap(aia_map, ar_lon, ar_lat, n_pix = n_pix)
        wav = aia_submap.meta['wavelnth']
        
        if save_submaps:
            fitsname = os.path.join(cropped_maps_folder, 'aia_lev1_nrt2_' + str(wav) + '_ar' + str(arnum) + '.fits')
            astropy.io.fits.writeto(fitsname, aia_submap.data, aia_submap.fits_header, output_verify='exception', overwrite=True, checksum=False)
        
        aia_submaps.append(aia_submap)
        
    return aia_submaps

#**********************************************************

def write_csv_em(file_name, time_em, total_em, function_csv='a'):
    """
    
    Function for saving the total EM values in a csv file (row by row)
    
    
    Parameters
        ----------
        file_name: string
            filename of teh csv file where the total EM values are saved
            
        time_em: string
            time corresponding to the total EM value to be saved
            
        total_em: float
            total EM value to be saved
        
        function_csv: string
            If function_csv=='w' a new file is created, otherwise a new row is appended into the existing file
            
    """
    
    header_csv = ['time_em', 'total_em']

    data = [time_em, total_em]

    with open(file_name, function_csv, encoding='UTF8', newline='') as file_csv:

            writer = csv.writer(file_csv)
            if function_csv == 'w':
                writer.writerow(header_csv)
            else:
                writer.writerow(data)

#**********************************************************

def convert_utc_to_timezone(this_datetime, timezone='US/Central'):
    """
    
    Function for converting input time to a specific time zone
    
    
    Parameters
        ----------
        this_datetime: datetime
            Time to be converted to a specific time zone
            
        timezone: string
            String containing the name of the refernce of the time zone to be used for the discussion
            
    Returns
        -------
        this_time_new_timezone: datetime
            Time converted to the refernce of the time zone
            
    """
    
    utc = pytz.timezone('UTC')
    new_timezone = pytz.timezone(timezone)
    #print(new_timezone)
    this_time_utc = utc.localize(this_datetime)
    this_time_new_timezone = this_time_utc.astimezone(new_timezone)
    
    return this_time_new_timezone                

#**********************************************************
    
def define_ssh_client():
    """
    
    Function for defining an ssh client object
    
    Returns
        ----------
        ssh_client: SSHClient object
            ssh client object used for uploading files via scp
            
    """
    
    ssh_host='physics.wku.edu'
    ssh_user='massa'
    ssh_password='FF_Proj'#'waffle!'
    
    ssh_client = SSHClient()
    ssh_client.load_system_host_keys()
    ssh_client.connect(ssh_host, username=ssh_user, password=ssh_password, look_for_keys=True)
    
    return ssh_client
    
#**********************************************************    

def ssh_scp_files(ssh_client, source_volume, destination_volume):
    """
    
    Function used for uploding files using via scp
    
    
    Parameters
        ----------
        ssh_client: SSHClient object
            ssh client object connected to the server
            
        source_volume: string
            path of the folder to be uploaded via scp
            
        destination_volume: string
            path of the folder where the files are uploaded via scp
            
    """
    
    with SCPClient(ssh_client.get_transport()) as scp:
        scp.put(source_volume, recursive=True, remote_path=destination_volume)        
        
#**********************************************************  
            
def select_data_to_download(start_time_series, grouped_wav, current_time_ut, wavelengths_needed):
    """
    
    Function used for selecting the latest AIA data to be downloaded
    
    
    Parameters
        ----------
        start_time_series: list
            list containing the start time of each cycle of AIA data that has been queried
        
        grouped_wav: list
            list containing the wavelength numbers of the AIA data in each 12s cycle
        
        current_time_ut: datetime
            Time of the latest data that have already been downloaded. It is used for donwloading only new data
        
        wavelengths_needed: list
            List containing the wavelengths of the AIA data that need to be downloaded
        
        
    Returns
        ----------
        idx: index of the 12s cycle of AIA data to be downloaded
            
    """
    
    idx  = len(start_time_series)-1
    this_start_time  = start_time_series[idx]
    this_grouped_wav = grouped_wav[idx]
    cond =  (this_start_time > current_time_ut) and \
            (np.sum(np.in1d(wavelengths_needed, this_grouped_wav)) == len(wavelengths_needed)) and \
            (len(this_grouped_wav)==len(wavelengths_needed)) 

    while (not cond) and (idx > -1):
        idx -= 1
        this_start_time  = start_time_series[idx]
        this_grouped_wav = grouped_wav[idx]
        cond =  (this_start_time > current_time_ut) and \
                (np.sum(np.in1d(wavelengths_needed, this_grouped_wav)) == len(wavelengths_needed)) and \
                (len(this_grouped_wav)==len(wavelengths_needed))

    return idx            


#**********************************************************
    
    
def create_animation_from_images(folder_name, animation_filename='animation.gif', fps=2):
    """
    
    Function used for creating a gif animation from the plots of the full-disk AIA images
    
    
    Parameters
        ----------
        folder_name: string
            path of the folder containing the png files that are used for creating the gif file 
        
        animation_filename: string
            File name of the gif file to be created
            
         fps: integer
             number of frames per second for the gif
            
    """
    
    # Get a list of PNG image files in the folder starting with "EM_"
    image_files = sorted(glob.glob(os.path.join(folder_name, '*.png')))

    if not image_files:
        raise ValueError("No image files found in the folder.")

    image_files = image_files[-10:]
    image_files.append(image_files[-1])
    image_files.append(image_files[-1])
    image_files.append(image_files[-1])
    
    # Load the first image to get the size
    with Image.open(image_files[0]) as img:
        width, height = img.size

    # Create a figure and axis to display the animation
    fig, ax = plt.subplots(figsize=(22,4.5))
    plt.subplots_adjust(top=1, bottom=0, left=0, right=1)
    ax.set_axis_off()
    # img_display = ax.imshow(Image.new('RGB', (width, height), color='white'), animated=True)
    img_display = ax.imshow(Image.new('RGB', (width, height), color='white'), animated=True)

    # Define the update function for the animation
    def update(frame):
        img = Image.open(image_files[frame])
        img_display.set_array(img)
        return [img_display]

    # Create the animation
    animation = FuncAnimation(fig, update, frames=len(image_files), interval=1000/fps)#, blit=True)

    # Save the animation as a GIF
    animation_path = os.path.join(animation_filename)
    animation.save(animation_path, writer='pillow',dpi=200)

    # Close the figure to free up resources
    plt.close(fig)

#**********************************************************   

def em_scale(y):
    """
    
    Function for scaling the high temperature EM maps
    
    
    Parameters
        ----------
        y: numpy array containing the high temperature EM map
            
        
    Returns
        ----------
        Scaled high temperature EM map
            
    """
    return y/1e50

#********************************************************** 

def em_unscale(y):
    """
    
    Function for unscaling the high temperature EM maps
    
    
    Parameters
        ----------
        y: numpy array containing the high temperature EM maps
            
        
    Returns
        ----------
        Unscaled high temperature EM maps
            
    """
    
    return 1e50*y

#********************************************************** 

def img_scale(x):
    """
    
    Function for scaling the AIA maps to be used for computing the high temperature EM maps by means of a linear combination of 
    the AIA channels
    
    
    Parameters
        ----------
        x: numpy array containing the AIA images to be scaled
            
        
    Returns
        ----------
        Scaled AIA maps
            
    """
    x2 = x
    bad = np.where(x2 <= 0.0)
    if len(bad[0]) >0:
        x2[bad] = 0.0
    return x2/2e4

#********************************************************** 

def img_unscale(x):
    """
    
    Function for unscaling the AIA maps to be used for computing the high temperature EM maps by means of a linear combination of 
    the AIA channels
    
    
    Parameters
        ----------
        x: numpy array containing the AIA images to be unscaled
            
        
    Returns
        ----------
        Unscaled AIA maps
            
    """
    return x*2e4

#********************************************************** 
    
def compute_em_map(aia_img, metadata, weights):
    """
    
    Function for computing the high temperature EM maps by means of a linear combination of the different AIA channels
    
    Parameters
        ----------
        aia_img: numpy array containing the AIA images to be used for computing the high temperature EM maps
        
        metadata: sunpy.util.metadata.MetaDict. Metadata to be used for making an EM map
        
        weights: list of floats to be used for computing the EM map by means of a linear combination of the AIA images
            
    Returns
        ----------
        High temperature EM map
            
    """
    
    dim = aia_img.shape
    
    em_map = np.zeros((dim[0],dim[1]))
    
    for i in range(len(weights)):
        em_map += img_scale(aia_img[:,:,i]) * weights[i]
    
    return Map(em_unscale(em_map), metadata)

#********************************************************** 
# def plot_results(plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum, i, file_name_em_csv, 
#                  timezone='US/Central'):
#     """
    
#     Function for plotting the high temperature EM map and the evolution of the high temperature total EM 
#     of a specific active region
    
#     Parameters
#         ----------
#         plots_folder: string
#             path of the folder where the plots are saved
            
#         aia_submaps: list
#             list containing the AIA submaps (around the considered active region) to be plotted
        
#         em_map: map
#             high temperature emission measure map to be plotted
            
#         xrsa_current:
#             latest GOES XRSA data to be plotted
            
#         xrsb_current:
#             latest GOES XRSB data to be plotted
            
#         arnum: int,
#             number of the considered active region
            
#         i: integer
#             index of the considered active region (1, 2, or 3). Used for defining the filename of the AR plot
        
#         file_name_em_csv: string
#             path of the csv file containing the total EM values for the considered AR
            
#         timezone: string
#             Name of the time zone considered for printing the time of the considered data
            
#     """
    
#     # Order aia maps with respect to temperature response
#     ordered_wav = [171,193,211,131,94]
    
#     wav_maps = []
#     for jj in range(5):
#         wav_maps.append(aia_submaps[jj].meta['wavelnth'])
#     wav_maps = np.array(wav_maps)
    
#     ordered_aia_maps = []
#     for jj in range(5):
#         idx = np.where(wav_maps == ordered_wav[jj])
#         ordered_aia_maps.append(aia_submaps[idx[0][0]])

#     xrsab_time = xrsa_current['time_tag']
#     goes_time_array  = []
    
#     for j in range(len(xrsab_time)):
        
#         this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
#         this_new_timezone_time = convert_utc_to_timezone(this_utc_time)
#         goes_time_array.append(this_new_timezone_time)
    
#     goes_time_array = np.array(goes_time_array)
#     goes_xrsa_flux  = xrsa_current['flux']
#     goes_xrsb_flux  = xrsb_current['flux']
    
#     # Plot AIA submaps
#     fig, ax = plt.subplots(figsize=(22,10))

#     ax1 = plt.subplot2grid((2,5), (0,0), colspan=1, projection=ordered_aia_maps[0])
#     ax2 = plt.subplot2grid((2,5), (0,1), colspan=1, projection=ordered_aia_maps[1])
#     ax3 = plt.subplot2grid((2,5), (0,2), colspan=1, projection=ordered_aia_maps[2])
#     ax4 = plt.subplot2grid((2,5), (0,3), colspan=1, projection=ordered_aia_maps[3])
#     ax5 = plt.subplot2grid((2,5), (0,4), colspan=1, projection=ordered_aia_maps[4])
#     ax6 = plt.subplot2grid((2,5), (1,0), colspan=2, projection=em_map)
#     ax7 = plt.subplot2grid((2,5), (1,2), colspan=3)
    
#     plt.subplots_adjust(left=0.1,
#                     bottom=0.1,
#                     right=0.9,
#                     top=0.9,
#                     wspace=0.4,
#                     hspace=0.4)
    
#     # Define axes list
#     ax = [ax1, ax2, ax3, ax4, ax5]
    
#     labelsize = 15
#     ticksize  = 15
#     chsize  = 15
#     legsize = 15
#     xlabel = "Solar X [arcsec]"
#     ylabel = "Solar Y [arcsec]"
#     for jj in range(5):
        
#         ordered_aia_maps[jj].plot(axes=ax[jj])
        
#         ax[jj].set_title('AIA ' + str(ordered_aia_maps[jj].meta['wavelnth']) + 'Å', fontsize=labelsize)
#         ax[jj].set_xlabel(xlabel,fontsize=labelsize)
#         ax[jj].set_ylabel(ylabel,fontsize=labelsize)
#         ax[jj].tick_params(axis='x', labelsize=ticksize)
#         ax[jj].tick_params(axis='y', labelsize=ticksize)
    
#     # Plot EM map
#     title  = 'AIA Emission Measure \n (T $\geq 10^{6.6}$ K)'
#     em_map.plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
#     em_map.plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')
    
#     im = em_map.plot(axes=ax6)

#     ax6.grid(False)
#     ax6.set_title(title,fontsize=labelsize)
#     ax6.set_xlabel(xlabel,fontsize=labelsize)
#     ax6.set_ylabel(ylabel,fontsize=labelsize)
#     ax6.tick_params(axis='x', labelsize=ticksize)
#     ax6.tick_params(axis='y', labelsize=ticksize)

#     cax = fig.add_axes([ax6.get_position().x1+0.01,ax6.get_position().y0,0.01,ax6.get_position().height])
#     cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
#     cbar.ax.tick_params(labelsize=labelsize) 
#     cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)
    
#     # Plot total EM and GOES
#     em_csv   = pd.read_csv(file_name_em_csv)
#     time_em  = np.array(em_csv['time_em'])
#     total_em = np.array(em_csv['total_em'])

#     # Define time array
#     time_em_array = []
#     for j in range(len(time_em)):
#         this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')        
#         this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#         time_em_array.append(this_new_timezone_time)

#     time_em_array      = np.array(time_em_array)
    
#     # Minimum and maximum times to be displayed in the plots
#     min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=25), np.min(goes_time_array)]))
#     max_time = np.max(goes_time_array)
    
#     # Make plot
#     ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
#     ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
#     ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
#     ax7.set_yscale('log')
#     ax7.tick_params(axis="x", labelsize=chsize)
#     ax7.tick_params(axis="y", labelsize=chsize)
#     ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%d-%m-%Y") + ')')
#     ax7.set(ylabel='GOES level')#
#     # ax7.set_title('AIA data time - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*2)
#     ax7.xaxis.label.set_size(chsize)
#     # ax7.set_xticks(goes_time_array[::2])
#     # ax7.set_xticklabels(goes_time_array[::2], rotation=45)
#     ax7.yaxis.label.set_size(chsize)
#     ax7.set_xlim((min_time,max_time))
#     ax7.set_ylim(1e-8, 1e-4)
#     ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
#     ax7.set_yticklabels(["A", "B", "C", "M", "X"])
#     #ax7.yticks(ticks=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4], labels=["A", "B", "C", "M", "X"])
#     ax7.grid(True)


#     color = 'black'
#     ax7.tick_params(axis='y', labelcolor=color)
#     ax7.yaxis.label.set_color(color)

#     ax8 = ax7.twinx()
#     ax8.plot(time_em_array,total_em, 'r', label='AIA EM')
#     ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax8.set_yscale('log')
#     ax8.set_ylim(1e46, 1e50)
#     ax8.set_xlim((min_time,max_time))
#     ax8.tick_params(axis="x", labelsize=chsize)
#     ax8.set(ylabel='EM [cm$^{-3}$]')
#     ax8.tick_params(axis="y", labelsize=chsize)
#     ax8.yaxis.label.set_size(chsize)
#     color = 'red'
#     ax8.tick_params(axis='y', labelcolor=color)
#     ax8.yaxis.label.set_color(color)
#     ax8.spines['right'].set_color(color)
#     #ax8.spines['left'].set_color('blue')
    
#     fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)
    
#     fig.suptitle('AR ' + str(arnum) + ' - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=25)

#     plt.savefig(os.path.join(plots_folder, 'aia_em_' + str(i))  , dpi=100,bbox_inches='tight')
def plot_results(plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum, label, i, file_name_em_csv, 
                 timezone='US/Central'):
    """
    
    Function for plotting the high temperature EM map and the evolution of the high temperature total EM 
    of a specific active region
    
    Parameters
        ----------
        plots_folder: string
            path of the folder where the plots are saved
            
        aia_submaps: list
            list containing the AIA submaps (around the considered active region) to be plotted
        
        em_map: map
            high temperature emission measure map to be plotted
            
        xrsa_current:
            latest GOES XRSA data to be plotted
            
        xrsb_current:
            latest GOES XRSB data to be plotted
            
        arnum: int,
            number of the considered active region
            
        i: integer
            index of the considered active region (1, 2, or 3). Used for defining the filename of the AR plot
        
        file_name_em_csv: string
            path of the csv file containing the total EM values for the considered AR
            
        timezone: string
            Name of the time zone considered for printing the time of the considered data
            
    """
    
    # Order aia maps with respect to temperature response
    ordered_wav = [171,193,211,131,94]
    
    wav_maps = []
    for jj in range(5):
        wav_maps.append(aia_submaps[jj].meta['wavelnth'])
    wav_maps = np.array(wav_maps)
    
    ordered_aia_maps = []
    for jj in range(5):
        idx = np.where(wav_maps == ordered_wav[jj])
        ordered_aia_maps.append(aia_submaps[idx[0][0]])

    xrsab_time = xrsa_current['time_tag']
    goes_time_array  = []
    
    for j in range(len(xrsab_time)):
        
        this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
        this_new_timezone_time = convert_utc_to_timezone(this_utc_time, timezone=timezone)
        goes_time_array.append(this_new_timezone_time)
    
    goes_time_array = np.array(goes_time_array)
    goes_xrsa_flux  = xrsa_current['flux']
    goes_xrsb_flux  = xrsb_current['flux']
    
    # Plot AIA submaps
    fig, ax = plt.subplots(figsize=(22,10))

    ax1 = plt.subplot2grid((2,5), (0,0), colspan=1, projection=ordered_aia_maps[0])
    ax2 = plt.subplot2grid((2,5), (0,1), colspan=1, projection=ordered_aia_maps[1])
    ax3 = plt.subplot2grid((2,5), (0,2), colspan=1, projection=ordered_aia_maps[2])
    ax4 = plt.subplot2grid((2,5), (0,3), colspan=1, projection=ordered_aia_maps[3])
    ax5 = plt.subplot2grid((2,5), (0,4), colspan=1, projection=ordered_aia_maps[4])
    ax6 = plt.subplot2grid((2,5), (1,0), colspan=2, projection=em_map)
    ax7 = plt.subplot2grid((2,5), (1,2), colspan=3)
    
    plt.subplots_adjust(left=0.1,
                    bottom=0.1,
                    right=0.9,
                    top=0.9,
                    wspace=0.4,
                    hspace=0.4)
    
    # Define axes list
    ax = [ax1, ax2, ax3, ax4, ax5]
    
    labelsize = 15
    ticksize  = 15
    chsize  = 15
    legsize = 15
    xlabel = "Solar X [arcsec]"
    ylabel = "Solar Y [arcsec]"
    for jj in range(5):
        
        ordered_aia_maps[jj].plot(axes=ax[jj])
        
        ax[jj].set_title('AIA ' + str(ordered_aia_maps[jj].meta['wavelnth']) + 'Å', fontsize=labelsize)
        ax[jj].set_xlabel(xlabel,fontsize=labelsize)
        ax[jj].set_ylabel(ylabel,fontsize=labelsize)
        ax[jj].tick_params(axis='x', labelsize=ticksize)
        ax[jj].tick_params(axis='y', labelsize=ticksize)
    
    # Plot EM map
    title  = 'AIA Emission Measure \n (T $\geq 10^{6.6}$ K)'
    em_map.plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
    em_map.plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')
    
    im = em_map.plot(axes=ax6)

    ax6.grid(False)
    ax6.set_title(title,fontsize=labelsize)
    ax6.set_xlabel(xlabel,fontsize=labelsize)
    ax6.set_ylabel(ylabel,fontsize=labelsize)
    ax6.tick_params(axis='x', labelsize=ticksize)
    ax6.tick_params(axis='y', labelsize=ticksize)

    cax = fig.add_axes([ax6.get_position().x1+0.01,ax6.get_position().y0,0.01,ax6.get_position().height])
    cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
    cbar.ax.tick_params(labelsize=labelsize) 
    cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)
    
    # Plot total EM and GOES
    em_csv   = pd.read_csv(file_name_em_csv)
    time_em  = np.array(em_csv['time_em'])
    total_em = np.array(em_csv['total_em'])

    # Define time array
    time_em_array = []
    for j in range(len(time_em)):
        this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')        
        this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
        time_em_array.append(this_new_timezone_time)

    time_em_array      = np.array(time_em_array)
    
    # Minimum and maximum times to be displayed in the plots
    min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=60), np.min(goes_time_array)]))
    max_time = np.max(goes_time_array)

    # Make plot
    ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
    ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
    ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
    ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    ax7.set_yscale('log')
    ax7.tick_params(axis="x", labelsize=chsize)
    ax7.tick_params(axis="y", labelsize=chsize)
    ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%m/%d/%Y") + ')')
    ax7.set(ylabel='GOES level')#
    # ax7.set_title('AIA data time - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*2)
    ax7.xaxis.label.set_size(chsize)
    # ax7.set_xticks(goes_time_array[::2])
    # ax7.set_xticklabels(goes_time_array[::2], rotation=45)
    ax7.yaxis.label.set_size(chsize)
    ax7.set_xlim((min_time,max_time))
    ax7.set_ylim(1e-8, 1e-4)
    ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
    ax7.set_yticklabels(["A", "B", "C", "M", "X"])
    #ax7.yticks(ticks=[1e-8, 1e-7, 1e-6, 1e-5, 1e-4], labels=["A", "B", "C", "M", "X"])
    ax7.grid(True)

    color = 'black'
    ax7.tick_params(axis='y', labelcolor=color)
    ax7.yaxis.label.set_color(color)

    ax8 = ax7.twinx()
    ax8.plot(time_em_array,total_em, 'r', label='AIA EM')
    ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
    ax8.set_yscale('log')
    ax8.set_ylim(1e46, 1e50)
    ax8.set_xlim((min_time,max_time))
    ax8.tick_params(axis="x", labelsize=chsize)
    ax8.set(ylabel='EM [cm$^{-3}$]')
    ax8.tick_params(axis="y", labelsize=chsize)
    ax8.yaxis.label.set_size(chsize)
    color = 'red'
    ax8.tick_params(axis='y', labelcolor=color)
    ax8.yaxis.label.set_color(color)
    ax8.spines['right'].set_color(color)
    #ax8.spines['left'].set_color('blue')
    
    fig.legend(bbox_to_anchor=(0.09, 0.05, 0.45, 0.38), fontsize=legsize)
    
    fig.suptitle(label+ " " + str(arnum) + ' - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=25)

    plt.savefig(os.path.join(plots_folder, 'aia_em_' + str(i))  , dpi=100,bbox_inches='tight')
    
#**********************************************************     
    
def load_realtime_XRS(goes_folder):
    """
    
    Function for loading the latest GOES XRS data (taken from https://github.com/pet00184/flarepred)
    
    Parameters
        ----------
        goes_folder: string
            path of the folder where the goes data are saved
            
    """

    json_url='https://services.swpc.noaa.gov/json/goes/primary/xrays-6-hour.json'
    json_file='xrays-6-hour.json'
    
    if os.path.exists(os.path.join(goes_folder, 'xrays-6-hour.json')):
        os.remove(os.path.join(goes_folder, 'xrays-6-hour.json'))
    wget.download(json_url, bar=None, out = goes_folder)
    with open(os.path.join(goes_folder, 'xrays-6-hour.json')) as f: 
        df = pd.DataFrame(json.load(f))
    #xrsa_current = df[df.energy == '0.05-0.4nm'].iloc[-30:]
    xrsa_current = df[df.energy == '0.05-0.4nm'].iloc[-100:]
    xrsa_current.reset_index(drop=True, inplace=True)
    #xrsb_current = df[df.energy == '0.1-0.8nm'] .iloc[-30:]
    xrsb_current = df[df.energy == '0.1-0.8nm'] .iloc[-100:]
    xrsb_current.reset_index(drop=True, inplace=True)
    #changing time_tag to datetime format: 
    xrsa_current.loc[:,'time_tag'] = pd.to_datetime(xrsa_current.loc[:,'time_tag'], format='%Y-%m-%dT%H:%M:%SZ')#, format='ISO8601')
    xrsb_current.loc[:,'time_tag'] = pd.to_datetime(xrsb_current.loc[:,'time_tag'], format='%Y-%m-%dT%H:%M:%SZ')#, format='ISO8601')
    
    return xrsa_current, xrsb_current
        
#********************************************************** 
# def plot_em_maps_and_curves(em_maps, total_em_folder,xrsa_current, xrsb_current,arnum,plots_folder,color_arr,ar_lon,ar_lat,
#                             timezone='US/Central'):
#     """
    
#     Function for plotting the high temperature EM maps and the evolution of the high temperature total EM 
#     curves for the considered active regions
    
#     Parameters
#         ----------
#         em_maps: list 
#             list containing the high temperature EM maps to be plotted
            
#         total_em_folder: string
#             path of the folder containing the cvs files with the time evolution of the total EM of the different ARs
            
#         xrsa_current:
#             latest GOES XRSA data to be plotted
            
#         xrsb_current:
#             latest GOES XRSB data to be plotted
            
#         arnum: list
#             list containing the number of the considered ARs
            
#         plots_folder: string
#             path of the folder where the plots are saved
            
#         color_arr: list of strings
#             colors that are used for plotting the boxes and the corresponnding lightcurves
            
#         timezone: string
#             Name of the time zone considered for printing the time of the considered data
            
#     """
    
#     xrsab_time = xrsa_current['time_tag']
#     goes_time_array  = []
    
#     for j in range(len(xrsab_time)):
        
#             this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
#             this_new_timezone_time = convert_utc_to_timezone(this_utc_time)
#             goes_time_array.append(this_new_timezone_time)
    
#     goes_time_array = np.array(goes_time_array)
#     goes_xrsa_flux  = xrsa_current['flux']
#     goes_xrsb_flux  = xrsb_current['flux']
    
#     # Plot AIA submaps
#     fig, ax = plt.subplots(figsize=(25,8))

#     ax1 = plt.subplot2grid((10,20), (0,0), rowspan=4, colspan=3, projection=em_maps[0])
#     ax2 = plt.subplot2grid((10,20), (0,4), rowspan=4, colspan=3, projection=em_maps[1])
#     ax3 = plt.subplot2grid((10,20), (0,8), rowspan=4, colspan=3, projection=em_maps[2])

#     ax4 = plt.subplot2grid((10,20), (5,0), rowspan=4, colspan=3, projection=em_maps[3])
#     ax5 = plt.subplot2grid((10,20), (5,4), rowspan=4, colspan=3, projection=em_maps[4])
#     ax6 = plt.subplot2grid((10,20), (5,8), rowspan=4, colspan=3, projection=em_maps[5])
    
    
#     ax7 = plt.subplot2grid((10,20), (1,13), rowspan=5, colspan=7)
    
#     plt.subplots_adjust(left=0.1,
#                         bottom=0.1,
#                         right=0.9,
#                         top=0.9,
#                         wspace=0.5,
#                         hspace=0.4)
    
#     # Define axes list
#     ax = [ax1, ax2, ax3, ax4, ax5, ax6, ax7]
    
#     labelsize = 15
#     ticksize  = 15
#     chsize  = 15
#     legsize = 15
#     xlabel = " "
#     ylabel = " "
    
#     for jj in range(len(arnum)):
        
#         #title  = 'AIA EM - AR ' + str(arnum[jj]) #+ ' \n (T $\geq 10^{6.6}$ K)'
#         title = 'AR ' + str(arnum[jj]) + ' ('+str(int(ar_lon[jj]))+','+str(int(ar_lat[jj]))+')'
#         em_maps[jj].plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
#         em_maps[jj].plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')

#         im = em_maps[jj].plot(axes=ax[jj])

#         ax[jj].grid(False)
#         ax[jj].set_title(title,fontsize=labelsize, color=color_arr[jj])
#         ax[jj].set_xlabel(xlabel,fontsize=labelsize)
#         ax[jj].set_ylabel(ylabel,fontsize=labelsize)
#         ax[jj].tick_params(axis='x', labelsize=ticksize)
#         ax[jj].tick_params(axis='y', labelsize=ticksize)
        
#         if jj==2 or jj==5:
        
#             cax = fig.add_axes([ax[jj].get_position().x1+0.01,ax[jj].get_position().y0,0.01,ax[jj].get_position().height])
#             cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
#             cbar.ax.tick_params(labelsize=labelsize) 
#             cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)
        
        
#     # Plot EM and GOES curves
#     em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[0])+'.csv'))
#     time_em  = np.array(em_csv['time_em'])
#     total_em = np.array(em_csv['total_em'])
    
#     # Define time array
#     time_em_array = []
#     for j in range(len(time_em)):
#         this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')        
#         this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#         time_em_array.append(this_new_timezone_time)

#     time_em_array = np.array(time_em_array)
    
#     # Minimum and maximum times to be displayed in the plots
#     min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=25), np.min(goes_time_array)]))
#     max_time = np.max(goes_time_array)
    
#     ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
#     ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
#     ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=5))
#     ax7.set_yscale('log')
#     ax7.tick_params(axis="x", labelsize=chsize)
#     ax7.tick_params(axis="y", labelsize=chsize)
#     ax7.set_title('Latest AIA data: - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*1.5)
#     ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%d-%m-%Y") + ')')
#     ax7.set(ylabel='GOES level')
#     ax7.xaxis.label.set_size(chsize)
#     ax7.yaxis.label.set_size(chsize)
#     ax7.set_xlim((min_time,max_time))
#     ax7.set_ylim(1e-8, 1e-4)
#     ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
#     ax7.set_yticklabels(["A", "B", "C", "M", "X"])
#     ax7.grid(True)


#     color = 'black'
#     ax7.tick_params(axis='y', labelcolor=color)
#     ax7.yaxis.label.set_color(color)

#     ax8 = ax7.twinx()
    
    
#     for i in range(len(arnum)):
#         em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[i])+'.csv'))
#         total_em = np.array(em_csv['total_em'])
#         time_em  = np.array(em_csv['time_em'])
#         # Define time array
#         time_em_array = []
#         for j in range(len(time_em)):
#             this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')
#             this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
#             time_em_array.append(this_new_timezone_time)
        
        
#         ax8.plot(time_em_array,total_em, color_arr[i], label='EM AR '+str(arnum[i]))
                               
#     ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
#     ax8.set_yscale('log')
#     ax8.set_ylim(1e46, 1e50)
#     ax8.set_xlim((min_time,max_time))
#     ax8.tick_params(axis="x", labelsize=chsize)
#     ax8.set(ylabel='EM [cm$^{-3}$]')
#     ax8.tick_params(axis="y", labelsize=chsize)
#     ax8.yaxis.label.set_size(chsize)
#     color = 'red'
#     ax8.tick_params(axis='y', labelcolor=color)
#     ax8.yaxis.label.set_color(color)
#     ax8.spines['right'].set_color(color)
#     #ax8.spines['left'].set_color('blue')
    
#     fig.legend(bbox_to_anchor=(0.4, -0.05, 0.45, 0.38), fontsize=legsize, ncol=2)

#     #plt.show()
    
#     plt.savefig(os.path.join(plots_folder, 'em_goes_plot')  , dpi=100,bbox_inches='tight')

def plot_em_maps_and_curves(em_maps, total_em_folder,xrsa_current, xrsb_current,arnum,label,plots_folder,color_arr,ar_lon,ar_lat,
                            timezone='US/Central'):
    """
    
    Function for plotting the high temperature EM maps and the evolution of the high temperature total EM 
    curves for the considered active regions
    
    Parameters
        ----------
        em_maps: list 
            list containing the high temperature EM maps to be plotted
            
        total_em_folder: string
            path of the folder containing the cvs files with the time evolution of the total EM of the different ARs
            
        xrsa_current:
            latest GOES XRSA data to be plotted
            
        xrsb_current:
            latest GOES XRSB data to be plotted
            
        arnum: list
            list containing the number of the considered ARs
            
        plots_folder: string
            path of the folder where the plots are saved
            
        color_arr: list of strings
            colors that are used for plotting the boxes and the corresponnding lightcurves
            
        timezone: string
            Name of the time zone considered for printing the time of the considered data
            
    """
    
    xrsab_time = xrsa_current['time_tag']
    goes_time_array  = []
    
    for j in range(len(xrsab_time)):
        
            this_utc_time        = xrsab_time[j].to_pydatetime()#datetime.fromtimestamp(xrsab_time[j])
            this_new_timezone_time = convert_utc_to_timezone(this_utc_time, timezone=timezone)
            goes_time_array.append(this_new_timezone_time)
    
    goes_time_array = np.array(goes_time_array)
    goes_xrsa_flux  = xrsa_current['flux']
    goes_xrsb_flux  = xrsb_current['flux']
    
    # Plot AIA submaps
    fig, ax = plt.subplots(figsize=(25,8))

    ax1 = plt.subplot2grid((10,20), (0,0), rowspan=4, colspan=3, projection=em_maps[0])
    ax2 = plt.subplot2grid((10,20), (0,4), rowspan=4, colspan=3, projection=em_maps[1])
    ax3 = plt.subplot2grid((10,20), (0,8), rowspan=4, colspan=3, projection=em_maps[2])

    ax4 = plt.subplot2grid((10,20), (5,0), rowspan=4, colspan=3, projection=em_maps[3])
    ax5 = plt.subplot2grid((10,20), (5,4), rowspan=4, colspan=3, projection=em_maps[4])
    ax6 = plt.subplot2grid((10,20), (5,8), rowspan=4, colspan=3, projection=em_maps[5])
    
    
    ax7 = plt.subplot2grid((10,20), (1,13), rowspan=5, colspan=7)
    
    plt.subplots_adjust(left=0.1,
                        bottom=0.1,
                        right=0.9,
                        top=0.9,
                        wspace=0.5,
                        hspace=0.4)
    
    # Define axes list
    ax = [ax1, ax2, ax3, ax4, ax5, ax6, ax7]
    
    labelsize = 15
    ticksize  = 15
    chsize  = 15
    legsize = 15
    xlabel = " "
    ylabel = " "
    
    for jj in range(len(arnum)):
        
        #title  = 'AIA EM - AR ' + str(arnum[jj]) #+ ' \n (T $\geq 10^{6.6}$ K)'
        title = label[jj] + " " + str(arnum[jj]) + ' ('+str(int(ar_lon[jj]))+','+str(int(ar_lat[jj]))+')'
        em_maps[jj].plot_settings['norm'] = colors.LogNorm(vmin=1e42, vmax=1e45, clip=True)
        em_maps[jj].plot_settings['cmap'] = matplotlib.cm.get_cmap('CMRmap')

        im = em_maps[jj].plot(axes=ax[jj])

        ax[jj].grid(False)
        ax[jj].set_title(title,fontsize=labelsize, color=color_arr[jj])
        ax[jj].set_xlabel(xlabel,fontsize=labelsize)
        ax[jj].set_ylabel(ylabel,fontsize=labelsize)
        ax[jj].tick_params(axis='x', labelsize=ticksize)
        ax[jj].tick_params(axis='y', labelsize=ticksize)
        
        if jj==2 or jj==5:
        
            cax = fig.add_axes([ax[jj].get_position().x1+0.01,ax[jj].get_position().y0,0.01,ax[jj].get_position().height])
            cbar = fig.colorbar(im,cax=cax)#,ticks=cbarticks)
            cbar.ax.tick_params(labelsize=labelsize) 
            cbar.ax.set_ylabel('EM [cm$^{-3}$ pixel$^{-1}$]',fontsize=labelsize)
        
        
    # Plot EM and GOES curves
    em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[0])+'.csv'))
    time_em  = np.array(em_csv['time_em'])
    total_em = np.array(em_csv['total_em'])
    
    # Define time array
    time_em_array = []
    for j in range(len(time_em)):
        this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')        
        this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
        time_em_array.append(this_new_timezone_time)

    time_em_array = np.array(time_em_array)
    
    # Minimum and maximum times to be displayed in the plots
    min_time = np.max(np.array([time_em_array[-1] - timedelta(minutes=60), np.min(goes_time_array)]))
    max_time = np.max(goes_time_array)
    
    ax7.plot(goes_time_array,goes_xrsa_flux, 'gray', label='GOES XRSA', linestyle='-.')
    ax7.plot(goes_time_array,goes_xrsb_flux, 'black', label='GOES XRSB', linestyle='dashed')
    ax7.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
    ax7.xaxis.set_major_locator(mdates.MinuteLocator(interval=10))
    ax7.set_yscale('log')
    ax7.tick_params(axis="x", labelsize=chsize)
    ax7.tick_params(axis="y", labelsize=chsize)
    ax7.set_title('Latest AIA data: - ' + time_em_array[-1].strftime("%H:%M:%S") + ' ' + timezone, fontsize=chsize*1.5)
    ax7.set(xlabel='Time (' + time_em_array[-1].strftime("%m/%d/%Y") + ')')
    ax7.set(ylabel='GOES level')
    ax7.xaxis.label.set_size(chsize)
    ax7.yaxis.label.set_size(chsize)
    ax7.set_xlim((min_time,max_time))
    ax7.set_ylim(1e-8, 1e-4)
    ax7.set_yticks([1e-8, 1e-7, 1e-6, 1e-5, 1e-4])
    ax7.set_yticklabels(["A", "B", "C", "M", "X"])
    ax7.grid(True)


    color = 'black'
    ax7.tick_params(axis='y', labelcolor=color)
    ax7.yaxis.label.set_color(color)

    ax8 = ax7.twinx()
    
    
    for i in range(len(arnum)):
        em_csv   = pd.read_csv(os.path.join(total_em_folder,'total_em_'+str(arnum[i])+'.csv'))
        total_em = np.array(em_csv['total_em'])
        time_em  = np.array(em_csv['time_em'])
        # Define time array
        time_em_array = []
        for j in range(len(time_em)):
            this_ut_time   = datetime.datetime.strptime(time_em[j], '%Y-%m-%dT%H:%M:%SZ')
            this_new_timezone_time = convert_utc_to_timezone(this_ut_time, timezone=timezone)
            time_em_array.append(this_new_timezone_time)
        
        
        ax8.plot(time_em_array,total_em, color_arr[i], label='EM '+ label[i] + " " +str(arnum[i]))
                               
    ax8.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=tz.gettz(timezone)))
    ax8.set_yscale('log')
    ax8.set_ylim(1e46, 1e50)
    ax8.set_xlim((min_time,max_time))
    ax8.tick_params(axis="x", labelsize=chsize)
    ax8.set(ylabel='EM [cm$^{-3}$]')
    ax8.tick_params(axis="y", labelsize=chsize)
    ax8.yaxis.label.set_size(chsize)
    color = 'red'
    ax8.tick_params(axis='y', labelcolor=color)
    ax8.yaxis.label.set_color(color)
    ax8.spines['right'].set_color(color)
    #ax8.spines['left'].set_color('blue')
    
    fig.legend(bbox_to_anchor=(0.4, -0.05, 0.45, 0.38), fontsize=legsize, ncol=2)

    #plt.show()
    
    plt.savefig(os.path.join(plots_folder, 'em_goes_plot')  , dpi=100,bbox_inches='tight')

#**********************************************************   

def plot_full_disk_images(calibrated_aia_maps, plots_folder, t_rec, arnum, ar_lon, ar_lat, color_arr,
                          timezone='US/Central', n_pix=1000):
    """
    
    Function for plotting the full-disk AIA images and the rectangles around the considered active regions
    
    
    Parameters
        ----------
        calibrated_aia_maps: list
            List of the calibrated full-disk AIA maps to be plotted
            
        plots_folder: string
            Path of the folder where the plots are saved
        
        t_rec: list
            List containing the times at which the AIA maps have been recorded
            
        arnum: list
            List of the number of the selected active regions
        
        ar_lon: float
            Longitude coordinates of the considered active regions (Heliographic Stonyhurst coordinates)
            
        ar_lat: float
            Latitude coordinates of the considered active regions (Heliographic Stonyhurst coordinates)
            
        timezone: string
            Name of the time zone w.r.t. the time are expressed
            
        n_pix: integer
            Number of pixels of the submaps extracted from the AIA maps. 
            It is used for plotting a rectangle around the considered active regions
            
        color_arr: list of strings
            colors that are used for plotting the boxes and the corresponnding lightcurves
            
    """

    ordered_wav = [171,193,211,131,94]
    
    wav_maps = []
    for jj in range(5):
        wav_maps.append(calibrated_aia_maps[jj].meta['wavelnth'])
    wav_maps = np.array(wav_maps)
    
    ordered_aia_maps = []
    for jj in range(5):
        idx = np.where(wav_maps == ordered_wav[jj])
        ordered_aia_maps.append(calibrated_aia_maps[idx[0][0]])
    
    fig, ax = plt.subplots(figsize=(22,4.5))

    ax1 = plt.subplot2grid((1,5), (0,0), colspan=1, projection=ordered_aia_maps[0])
    ax2 = plt.subplot2grid((1,5), (0,1), colspan=1, projection=ordered_aia_maps[1])
    ax3 = plt.subplot2grid((1,5), (0,2), colspan=1, projection=ordered_aia_maps[2])
    ax4 = plt.subplot2grid((1,5), (0,3), colspan=1, projection=ordered_aia_maps[3])
    ax5 = plt.subplot2grid((1,5), (0,4), colspan=1, projection=ordered_aia_maps[4])
    
    plt.subplots_adjust(left=0.1,
                    bottom=0.1,
                    right=0.9,
                    top=0.9,
                    wspace=0.4,
                    hspace=0.1)
    
    
    # Plot AIA submaps
    ax = [ax1, ax2, ax3, ax4, ax5]
    
    labelsize = 10
    ticksize  = 10
    chsize  = 10
    legsize = 10
    xlabel = "Solar X [arcsec]"
    ylabel = "Solar Y [arcsec]"
    
    transparent_white = (1, 1, 1, 0.5)
    for jj in range(5):
        
        this_map = ordered_aia_maps[jj]
        this_map = normalize_exposure(this_map)
        
        vmin = 0.3
        vmax = 16000./2.9
        this_map.plot_settings['norm'] = colors.LogNorm(vmin=vmin, vmax=vmax, clip=True)
        this_map.plot_settings['cmap'] = matplotlib.cm.get_cmap('gray')
        
        this_map.plot(axes=ax[jj])

        ax[jj].set_title('AIA ' + str(this_map.meta['wavelnth']) + 'Å', fontsize=labelsize)
        ax[jj].set_xlabel(xlabel,fontsize=labelsize)
        ax[jj].set_ylabel(ylabel,fontsize=labelsize)
        ax[jj].tick_params(axis='x', labelsize=ticksize)
        ax[jj].tick_params(axis='y', labelsize=ticksize)
        
        for ii in range(len(ar_lon)):
            
            this_coord = SkyCoord(ar_lon[ii]*u.deg, ar_lat[ii]*u.deg, frame=frames.HeliographicStonyhurst)

            pix_x = this_map.world_to_pixel(this_coord).x.value
            pix_y = this_map.world_to_pixel(this_coord).y.value

            top_right   = this_map.pixel_to_world((pix_x+n_pix//2-1)*u.pix,(pix_y+n_pix//2-1)*u.pix)
            bottom_left = this_map.pixel_to_world((pix_x-n_pix//2)*u.pix,(pix_y-n_pix//2)*u.pix)

            new_bl = SkyCoord(bottom_left.Tx, bottom_left.Ty, frame=this_map.coordinate_frame)
            new_tr = SkyCoord(top_right.Tx, top_right.Ty, frame=this_map.coordinate_frame)
            
            this_map.draw_quadrangle(
            new_bl,
            axes=ax[jj],
            top_right=new_tr,
            color=color_arr[ii],
            linewidth=2,
            )
            
    current_time = convert_utc_to_timezone(datetime.datetime.strptime(t_rec[0], '%Y-%m-%dT%H:%M:%SZ'), timezone=timezone)
    
    fig.suptitle('AIA data ' + current_time.strftime("%m/%d/%Y - %H:%M:%S") + ' ' + timezone, fontsize=25)

    plt.savefig(os.path.join(plots_folder, 'aia_full_disk_'+current_time.strftime("%Y-%m-%dT%H%M%S")+'.png'), 
                dpi=200,bbox_inches='tight')

#**********************************************************   
    
def calibrate_aia_data(aia_maps, correction_table):
    """
    
    Function for calibrating the AIA maps to be used for computing the high temperature total EM map
    The AIA mas are normalized by the exposure time and corrected for the degration of the instrument
    
    Parameters
        ----------
        aia_maps: list 
            list containing the high temperature EM maps to be plotted
            
        correction_table: table to be used for correcting the degradation of the instrument. 
                          Created with the module correct_degradation from aiapy.calibrate
        
    Returns
        ----------
        Calibrated AIA maps
            
    """
    
    aia_img = []
    for aia_map in aia_maps:
        aia_map = correct_degradation(normalize_exposure(aia_map), correction_table=correction_table)
        aia_img.append(aia_map.data)
        
    aia_img = np.array(aia_img)
    aia_img = np.transpose(aia_img, (1,2,0))
    
    return aia_img      

#**********************************************************
# def stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum, 
#                     correction_table, timezone='US/Central', n_pix=1000, latency=10, 
#                     reference_wav=193, th_tot_em=0,
#                     weights = [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06], save_maps=False):
#     """
    
#     Function for downloading near real time AIA data, computing the high temperature EM maps and plot the results on the WKU website
    
#     Parameters
#         ----------
        
#         duration_stream: int. Duration of the data stream in minutes

#         data_folder: string. Path of the folder where the data are saved

#         ar_lon: list of float numbers. It contains the longitude coordinates (degrees) of center of each active region

#         ar_lat: list of float numbers. It contains the latitude coordinates (degrees) of center of each active region 

#         arnum: list of integers. It contains the ID number of the considered active regions
        
#         correction_table: table to be used for correcting the degradation of the instrument. 
#                           Created with the module correct_degradation from aiapy.calibrate

#     Keywords
#         ----------
        
#         timezone: string. Name of the timezone with respect to which the time is expressed. Default, 'US/Central'
                  
#         n_pix: int. Number of pixels of the submaps that are extracted around each AR from the (near-realtime) full-disk AIA maps. Default, 1000 [pixels]

#         latency: int. Number of minutes of past data that we query at every iteration of the pipeline (to be sure to get the latest data). Default, 10 [minutes]

#         reference_wav: int. Reference wavelength to be considered for determining the 12s "cycles" of AIA data. Default, 193 [A]
        
#         th_tot_em: float. Threshold value that is considered for computing the total high temperature EM curves from the corresponding maps.
#                    Before summing, the pixel values below the threshold are set to 0. Default, 0 [cm^-3]
        
#         weights: list, weights that are used for performing the linear combination of the AIA channels to obtain the 
#                  high temperature EM maps. Default, [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06]
        
#         ssh_host: string, name of the server where the plots are uploaded via scp
        
#         ssh_user: string, name of the user on the server where the plots are uploaded via scp
        
#         ssh_password: string, password of the user on the server where the plots are uploaded via scp
                    
#         destination_volume: string, path of the folder on the server where the plots are uploaded via scp
        
#     """
    
#     ############ INITIALIZE PARAMETERS AND MAKE FOLDERS
    
#     # Number of the considered active regions (ARs). 
#     # The pipeline has been implemented so that it considers 3 ARs at the same time
#     n_ar = 6 
    
#     # Check that the number of parameters is correct
#     if len(ar_lon) < n_ar:
#         raise Exception("The number of elements in ar_lon is less than " + str(n_ar))
    
#     if len(ar_lat) < n_ar:
#         raise Exception("The number of elements in ar_lat is less than " + str(n_ar))
        
#     if len(arnum) < n_ar:
#         raise Exception("The number of elements in arnum is less than " + str(n_ar))
    
#     # Define colors that will be used for plotting the boxes and the corresponding curves
#     color_arr=['red','gold','blue', 'lime', 'cyan', 'magenta']
    
#     # Define JSOC server client
#     client = configure_jsoc_server()
    
#     # Plots folder
#     plots_folder = os.path.join(data_folder, 'all_plots')
#     mkdir(plots_folder)
    
#     # Latest results folder
#     latest_plots_folder = os.path.join(data_folder, 'latest_plots')
#     mkdir(latest_plots_folder)
    
#     # AIA data folder
#     aia_data_folder = os.path.join(data_folder, 'aia_data_folder')
#     mkdir(aia_data_folder)
    
#     # GOES folder
#     goes_folder = os.path.join(data_folder, 'goes_data_folder')
#     mkdir(goes_folder)
    
#     # Total EM folder
#     total_em_folder = os.path.join(data_folder, 'total_em')
#     mkdir(total_em_folder)
#     for i in range(len(arnum)):
#         file_name_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
#         if not os.path.exists(file_name_csv):
#             write_csv_em(file_name_csv, 0, 0, function_csv='w')
    
#     # Array containing the wavelengths needed to compute the high temperature EM maps
#     wavelengths_needed = np.array([94, 131, 171, 193, 211])
    
#     # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
#     start_time_ut    = datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes = latency)
#     start_time_ut_time_diff = datetime.datetime.now(datetime.timezone.utc)
#     current_time_ut  = start_time_ut
#     time_diff = 0
    
#     # Define utc time zone
#     utc = pytz.timezone('UTC')
    
#     # Define ssh client to be used for uploading data
#     destination_volume='/server/html/waffle/'
#     ssh_client = define_ssh_client()
    
#     ############ START STREAM
    
#     while time_diff <= duration_stream:

#         # Query data
#         query, segments = client.query('aia.lev1_nrt2[' + current_time_ut.strftime("%Y.%m.%d_%H:%M:%S") + '_UT/' + str(latency) + 'm]',  key='T_REC, WAVELNTH', seg='image_lev1')

#         # Extract wavelengths, time of the measurement, segment link 
#         wavelnth = np.array(query['WAVELNTH'])
#         t_rec    = np.array(query['T_REC'])
#         segments = np.squeeze(np.array(segments))

#         # Check if reference wavelength is present in the set of data that have been queried
#         idx = np.where(wavelnth == reference_wav)
#         idx = idx[0]

#         if len(idx) == 0:
#             print("Reference wavelength not found. Wait 15 s.")
#             time.sleep(15)
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             continue

#         # Divide data into cycles
#         grouped_wav       = []
#         grouped_t_rec     = []
#         grouped_segments  = []
#         start_time_series = []

#         # Divide data into 12s cycles
#         for start, end in zip(idx, idx[1:]):

#             this_wav   = wavelnth[start:end]
#             this_t_rec = t_rec[start:end]
#             this_segments = segments[start:end]
#             this_start_time = datetime.datetime.strptime(this_t_rec[0], '%Y-%m-%dT%H:%M:%SZ')
#             start_time_series.append(utc.localize(this_start_time))

#             # Remove 335 A, 304 A, 1600 A, 1700 A and 4500 A
#             idx_remove = np.where((this_wav == 304) | (this_wav == 335) | (this_wav == 1600) | (this_wav == 1700) | (this_wav == 4500))
#             idx_remove = idx_remove[0]
#             if len(idx_remove) > 0:
#                 this_wav      = np.delete(this_wav, idx_remove)
#                 this_t_rec    = np.delete(this_t_rec, idx_remove)
#                 this_segments = np.delete(this_segments, idx_remove)

#             grouped_wav.append(this_wav)
#             grouped_t_rec.append(this_t_rec)
#             grouped_segments.append(this_segments)

        
#         start_time_series = np.array(start_time_series)
        
#         # Select latest complete 12s cycle to be downloaded
#         idx = select_data_to_download(start_time_series, grouped_wav, current_time_ut, wavelengths_needed)
        
#         if idx >= 0:
            
#             # Take the last 12s AIA data cycle
#             grouped_wav       = grouped_wav[idx]
#             grouped_t_rec     = grouped_t_rec[idx]
#             grouped_segments  = grouped_segments[idx]
#             start_time_series = start_time_series[idx]
        
#             # Keep track of the elapsed time
#             t = time.time()
            
#             # Download and calibrate full-disk near real time AIA maps
#             aia_maps, dowloaded_data_folder, error = download_aia_data(grouped_wav, grouped_t_rec, grouped_segments, aia_data_folder, timezone=timezone)
#             calibrated_aia_maps = calibrate_full_disk_maps(aia_maps)
      
#             if error:
#                 print("Error in downloading data. Continue..")
#                 time.sleep(30)
#                 continue
            
#             # Crop images around ARs and compute EM of the "hottest region"
#             cropped_maps_folder = dowloaded_data_folder + "_crop"
#             if save_maps:
#                 mkdir(cropped_maps_folder)
            
#             # Plot full-disk maps
#             plot_full_disk_images(calibrated_aia_maps,plots_folder,grouped_t_rec,arnum,ar_lon,ar_lat,color_arr,timezone=timezone, n_pix=n_pix)
            
#             # Create gif animation
#             create_animation_from_images(plots_folder, animation_filename=os.path.join(latest_plots_folder,'full_disk_maps.gif'), fps=2)
            
#             # Download latest GOES data
#             xrsa_current, xrsb_current = load_realtime_XRS(goes_folder)
            
#             em_maps = []
#             for i in range(n_ar):
#                 # Crop images around active regions
#                 aia_submaps = crop_full_disk_maps(calibrated_aia_maps, ar_lon[i], ar_lat[i], arnum[i], cropped_maps_folder, n_pix=n_pix, save_submaps=save_maps)
                
#                 metadata = aia_submaps[0].meta
#                 # Calibrate AIA maps (correct degradation and normalize exposure)
#                 aia_img = calibrate_aia_data(aia_submaps, correction_table)
                
#                 # Compute high temperature EM maps
#                 em_map = compute_em_map(aia_img, metadata, weights)
#                 if save_maps:
#                     fitsname = os.path.join(cropped_maps_folder, 'em_map_ar' + str(arnum[i]) + '.fits')
#                     astropy.io.fits.writeto(fitsname, em_map.data, em_map.fits_header, output_verify='exception', overwrite=True, checksum=False)    
#                 em_maps.append(em_map)
                
#                 # Save EM values in csv
#                 file_name_em_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
#                 em_map_th = em_map.data
#                 idx = np.where(em_map_th < th_tot_em) # set values below the treshold equal to 0
#                 em_map_th[idx] = 0
#                 write_csv_em(file_name_em_csv, grouped_t_rec[0], np.sum(em_map_th))
                
#                 plot_results(latest_plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum[i], i+1, file_name_em_csv, 
#                              timezone=timezone)

            
#             # Plot GOES and AIA curves
#             plot_em_maps_and_curves(em_maps,total_em_folder,xrsa_current, xrsb_current,arnum,latest_plots_folder,color_arr,ar_lon,ar_lat,timezone=timezone)
            
#             print("Upload data...")
#             ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
#             print("Upload completed!")
            
#             if not save_maps:
#                 shutil.rmtree(dowloaded_data_folder)
            
#             elapsed = time.time() - t
#             print('Elapsed time: ' + str(round(elapsed)) + ' s')
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             # Reset 'current_time_ut'
#             current_time_ut = start_time_series
            
#         else:
#             print("No new data series. Wait 15 s.")
#             time.sleep(15)
#             time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
#             time_diff = time_diff.seconds/60
#             continue

def stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum, label, 
                    correction_table, timezone='US/Central', n_pix=1000, latency=10, 
                    reference_wav=193, th_tot_em=0,
                    weights = [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06], save_maps=False):
    """
    
    Function for downloading near real time AIA data, computing the high temperature EM maps and plot the results on the WKU website
    
    Parameters
        ----------
        
        duration_stream: int. Duration of the data stream in minutes

        data_folder: string. Path of the folder where the data are saved

        ar_lon: list of float numbers. It contains the longitude coordinates (degrees) of center of each active region

        ar_lat: list of float numbers. It contains the latitude coordinates (degrees) of center of each active region 

        arnum: list of integers. It contains the ID number of the considered active regions
        
        correction_table: table to be used for correcting the degradation of the instrument. 
                          Created with the module correct_degradation from aiapy.calibrate

    Keywords
        ----------
        
        timezone: string. Name of the timezone with respect to which the time is expressed. Default, 'US/Central'
                  
        n_pix: int. Number of pixels of the submaps that are extracted around each AR from the (near-realtime) full-disk AIA maps. Default, 1000 [pixels]

        latency: int. Number of minutes of past data that we query at every iteration of the pipeline (to be sure to get the latest data). Default, 10 [minutes]

        reference_wav: int. Reference wavelength to be considered for determining the 12s "cycles" of AIA data. Default, 193 [A]
        
        th_tot_em: float. Threshold value that is considered for computing the total high temperature EM curves from the corresponding maps.
                   Before summing, the pixel values below the threshold are set to 0. Default, 0 [cm^-3]
        
        weights: list, weights that are used for performing the linear combination of the AIA channels to obtain the 
                 high temperature EM maps. Default, [1.20196640e-04,  2.12817313e-05, -7.33613022e-07,  1.83818002e-07, -1.90719161e-06]
        
        ssh_host: string, name of the server where the plots are uploaded via scp
        
        ssh_user: string, name of the user on the server where the plots are uploaded via scp
        
        ssh_password: string, password of the user on the server where the plots are uploaded via scp
                    
        destination_volume: string, path of the folder on the server where the plots are uploaded via scp
        
    """
    
    ############ INITIALIZE PARAMETERS AND MAKE FOLDERS
    
    # Number of the considered active regions (ARs). 
    # The pipeline has been implemented so that it considers 3 ARs at the same time
    n_ar = 6 
    
    # Check that the number of parameters is correct
    if len(ar_lon) < n_ar:
        raise Exception("The number of elements in ar_lon is less than " + str(n_ar))
    
    if len(ar_lat) < n_ar:
        raise Exception("The number of elements in ar_lat is less than " + str(n_ar))
        
    if len(arnum) < n_ar:
        raise Exception("The number of elements in arnum is less than " + str(n_ar))
    
    # Define colors that will be used for plotting the boxes and the corresponding curves
    color_arr=['red','gold','blue', 'lime', 'cyan', 'magenta']
    
    # Define JSOC server client
    client = configure_jsoc_server()
    
    # Plots folder
    plots_folder = os.path.join(data_folder, 'all_plots')
    mkdir(plots_folder)
    
    # Latest results folder
    latest_plots_folder = os.path.join(data_folder, 'latest_plots')
    mkdir(latest_plots_folder)
    
    # AIA data folder
    aia_data_folder = os.path.join(data_folder, 'aia_data_folder')
    mkdir(aia_data_folder)
    
    # GOES folder
    goes_folder = os.path.join(data_folder, 'goes_data_folder')
    mkdir(goes_folder)
    
    # Total EM folder
    total_em_folder = os.path.join(data_folder, 'total_em')
    mkdir(total_em_folder)
    for i in range(len(arnum)):
        file_name_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
        if not os.path.exists(file_name_csv):
            write_csv_em(file_name_csv, 0, 0, function_csv='w')
    
    # Array containing the wavelengths needed to compute the high temperature EM maps
    wavelengths_needed = np.array([94, 131, 171, 193, 211])
    
    # Initialize start time, current time and difference between start time and current time (zero at the beginning of the stream)
    start_time_ut    = datetime.datetime.now(datetime.timezone.utc) - timedelta(minutes = latency)
    start_time_ut_time_diff = datetime.datetime.now(datetime.timezone.utc)
    current_time_ut  = start_time_ut
    time_diff = 0
    
    # Define utc time zone
    utc = pytz.timezone('UTC')
    
    # Define ssh client to be used for uploading data
    destination_volume='/server/html/waffle/'
    ssh_client = define_ssh_client()
    
    ############ START STREAM
    
    while time_diff <= duration_stream:

        # Query data
        query, segments = client.query('aia.lev1_nrt2[' + current_time_ut.strftime("%Y.%m.%d_%H:%M:%S") + '_UT/' + str(latency) + 'm]',  key='T_REC, WAVELNTH', seg='image_lev1')

        # Extract wavelengths, time of the measurement, segment link 
        wavelnth = np.array(query['WAVELNTH'])
        t_rec    = np.array(query['T_REC'])
        segments = np.squeeze(np.array(segments))

        # Check if reference wavelength is present in the set of data that have been queried
        idx = np.where(wavelnth == reference_wav)
        idx = idx[0]

        if len(idx) == 0:
            print("Reference wavelength not found. Wait 15 s.")
            time.sleep(15)
            time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            time_diff = time_diff.seconds/60
            continue

        # Divide data into cycles
        grouped_wav       = []
        grouped_t_rec     = []
        grouped_segments  = []
        start_time_series = []

        # Divide data into 12s cycles
        for start, end in zip(idx, idx[1:]):

            this_wav   = wavelnth[start:end]
            this_t_rec = t_rec[start:end]
            this_segments = segments[start:end]
            this_start_time = datetime.datetime.strptime(this_t_rec[0], '%Y-%m-%dT%H:%M:%SZ')
            start_time_series.append(utc.localize(this_start_time))

            # Remove 335 A, 304 A, 1600 A, 1700 A and 4500 A
            idx_remove = np.where((this_wav == 304) | (this_wav == 335) | (this_wav == 1600) | (this_wav == 1700) | (this_wav == 4500))
            idx_remove = idx_remove[0]
            if len(idx_remove) > 0:
                this_wav      = np.delete(this_wav, idx_remove)
                this_t_rec    = np.delete(this_t_rec, idx_remove)
                this_segments = np.delete(this_segments, idx_remove)

            grouped_wav.append(this_wav)
            grouped_t_rec.append(this_t_rec)
            grouped_segments.append(this_segments)

        
        start_time_series = np.array(start_time_series)
        
        # Select latest complete 12s cycle to be downloaded
        idx = select_data_to_download(start_time_series, grouped_wav, current_time_ut, wavelengths_needed)
        
        if idx >= 0:
            
            # Take the last 12s AIA data cycle
            grouped_wav       = grouped_wav[idx]
            grouped_t_rec     = grouped_t_rec[idx]
            grouped_segments  = grouped_segments[idx]
            start_time_series = start_time_series[idx]
        
            # Keep track of the elapsed time
            t = time.time()
            
            # Download and calibrate full-disk near real time AIA maps
            aia_maps, dowloaded_data_folder, error = download_aia_data(grouped_wav, grouped_t_rec, grouped_segments, aia_data_folder, timezone=timezone)
            calibrated_aia_maps = calibrate_full_disk_maps(aia_maps)
      
            if error:
                print("Error in downloading data. Continue..")
                time.sleep(30)
                continue
            
            # Crop images around ARs and compute EM of the "hottest region"
            cropped_maps_folder = dowloaded_data_folder + "_crop"
            if save_maps:
                mkdir(cropped_maps_folder)
            
            # Plot full-disk maps
            plot_full_disk_images(calibrated_aia_maps,plots_folder,grouped_t_rec,arnum,ar_lon,ar_lat,color_arr,timezone=timezone, n_pix=n_pix)
            
            # Create gif animation
            create_animation_from_images(plots_folder, animation_filename=os.path.join(latest_plots_folder,'full_disk_maps.gif'), fps=2)
            
            # Download latest GOES data
            xrsa_current, xrsb_current = load_realtime_XRS(goes_folder)
            
            em_maps = []
            for i in range(n_ar):
                # Crop images around active regions
                aia_submaps = crop_full_disk_maps(calibrated_aia_maps, ar_lon[i], ar_lat[i], arnum[i], cropped_maps_folder, n_pix=n_pix, save_submaps=save_maps)
                
                metadata = aia_submaps[0].meta
                # Calibrate AIA maps (correct degradation and normalize exposure)
                aia_img = calibrate_aia_data(aia_submaps, correction_table)
                
                # Compute high temperature EM maps
                em_map = compute_em_map(aia_img, metadata, weights)
                if save_maps:
                    fitsname = os.path.join(cropped_maps_folder, 'em_map_ar' + str(arnum[i]) + '.fits')
                    astropy.io.fits.writeto(fitsname, em_map.data, em_map.fits_header, output_verify='exception', overwrite=True, checksum=False)    
                em_maps.append(em_map)
                
                # Save EM values in csv
                file_name_em_csv = os.path.join(total_em_folder, 'total_em_' + str(arnum[i]) + '.csv')
                em_map_th = em_map.data
                idx = np.where(em_map_th < th_tot_em) # set values below the treshold equal to 0
                em_map_th[idx] = 0
                write_csv_em(file_name_em_csv, grouped_t_rec[0], np.sum(em_map_th))
                
                plot_results(latest_plots_folder, aia_submaps, em_map, xrsa_current, xrsb_current, arnum[i], label[i], i+1, file_name_em_csv, 
                             timezone=timezone)

            
            # Plot GOES and AIA curves
            plot_em_maps_and_curves(em_maps,total_em_folder,xrsa_current, xrsb_current,arnum,label,latest_plots_folder,color_arr,ar_lon,ar_lat,timezone=timezone)
            
            print("Upload data...")
            ssh_scp_files(ssh_client, latest_plots_folder, destination_volume)
            print("Upload completed!")
            
            if not save_maps:
                shutil.rmtree(dowloaded_data_folder)
            
            elapsed = time.time() - t
            print('Elapsed time: ' + str(round(elapsed)) + ' s')
            time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            time_diff = time_diff.seconds/60
            # Reset 'current_time_ut'
            current_time_ut = start_time_series
            
        else:
            print("No new data series. Wait 15 s.")
            time.sleep(15)
            time_diff = datetime.datetime.now(datetime.timezone.utc) - start_time_ut_time_diff
            time_diff = time_diff.seconds/60
            continue

