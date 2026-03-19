import warnings
warnings.filterwarnings("ignore")

from scipy.io.idl import readsav
import os

#import dem_rml
import aux_functions
import numpy as np
from aiapy.calibrate.util import get_correction_table as get_correction_table

if __name__=="__main__":
    
    # Define folder where to save the data
    today = '2026Feb5'
    data_folder = os.path.join('.', today)
    aux_functions.mkdir(data_folder)
    
    # AR parameters, top three first, then bottom three
    rsun=1000 # radius of solar disk in arcsec
    label_top=["A", "B", "C"]
    
    arnum_top=[4367,4366,4358]# active region numbers
    
    x_top = np.array([-200,450,800]) # heliographic X
    y_top = np.array([300,250,300]) # heliographic Y
    lat_top=(180/np.pi)*np.arcsin(y_top/rsun)
    long_top=(180/np.pi)*np.arcsin(x_top/(rsun*np.cos((np.pi/180)*lat_top)))
       
    #lat_top=[23, -15, 21]# active region latitude in degrees - original line
    #long_top=[29, 15, 53]# active region longitude in degrees - orginal line
    
    # box_x_top = [200,200,100] # widths of boxes (in pixel units)
    # box_y_top = [100,100,200] # heights of boxes (in pixel units)
    #These positions are for the southern region
    label_bottom=["D", "E", "F"]
        
    arnum_bottom=[4371,4369,4362]# active region numbers
    
    x_bottom = np.array([-550,-400,200]) # heliographic X
    y_bottom = np.array([-400,0,-400]) # heliographic Y
    lat_bottom=(180/np.pi)*np.arcsin(y_bottom/rsun)
    long_bottom=(180/np.pi)*np.arcsin(x_bottom/(rsun*np.cos((np.pi/180)*lat_bottom)))
    
    #lat_bottom=[2, -28, -10]# active region latitude in degrees - BA
    #long_bottom=[0, 15, 75]# active region longitude in degrees - BA
    
    # box_x_bottom = [200,200,100] # widths of boxes (in arcsec units)
    # box_y_bottom = [100,100,200] # heights of boxes (in arcsec units)
    label=label_top+label_bottom
    arnum=arnum_top+arnum_bottom
    ar_lat=np.concatenate((lat_top,lat_bottom))
    ar_lon=np.concatenate((long_top,long_bottom))
    
    # box_x = box_x_top + box_x_bottom
    # box_y = box_y_top + box_y_bottom
       
    # arnum  = [3624, 3626, 3622, 1, 0, 3620]
    # ar_lat = [15, 11, 11, -15, +15, -8] #North and South
    # ar_lon = [-30, 33, 53, -15, -55, 66] #West and East 
    # #If boxes are not used, move to ~,80

    # Normalization of light curves: multiply by 1000^2 / (w*h) [ or 500^2 / (w * h ) ]
    
    # Duration of the current session of the data stream
    duration_stream = 480 # minutes

    # Timezone with respect to which the times are expressed in the plots
    timezone='US/Central'#'US/Mountain'#'US/Alaska'#
    
    # Boolean: if True, the fits files of the downloaded AIA maps and of the EM maps that are computed from the AIA data are saved.
    save_maps=False
    
    # Read correction table
    correction_table = get_correction_table(correction_table=os.path.join(".","tables","aia_V10_20201119_190000_response_table.txt"))
    
    # Start AIA data stream
    aux_functions.stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum, label, correction_table, timezone=timezone, n_pix_x=500, n_pix_y=500, save_maps=save_maps)
    #aux_functions.stream_aia_data(duration_stream, data_folder, ar_lon, ar_lat, arnum, label, correction_table, timezone=timezone, n_pix_x=1000, n_pix_y=1000, save_maps=save_maps)
    