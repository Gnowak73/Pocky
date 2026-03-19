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

import sys
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

# def extract_submap(aia_map, ar_lon, ar_lat, n_pix = 500): #### old (working) version
def extract_submap(aia_map, ar_lon, ar_lat, n_pix = 700):
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
    # The pipeline has been implemented so that it considers 6 ARs at the same time
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
    #client = configure_jsoc_server()
    
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
    
    # Define utc time zone
    utc = pytz.timezone('UTC')
    
    ############ START STREAM
        
        if idx >= 0:
            
            # Download and calibrate full-disk near real time AIA maps
            aia_maps, dowloaded_data_folder, error = download_aia_data(grouped_wav, grouped_t_rec, grouped_segments, aia_data_folder, timezone=timezone)
            calibrated_aia_maps = calibrate_full_disk_maps(aia_maps)
            #print(aia_maps)
            
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
            