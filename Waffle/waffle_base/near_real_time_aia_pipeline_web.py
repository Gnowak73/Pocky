import warnings
warnings.filterwarnings("ignore")

from scipy.io.idl import readsav
import os

#import dem_rml
import aux_functions_web
from aiapy.calibrate.util import get_correction_table as get_correction_table

if __name__=="__main__":
    
    # Define folder where to save the data
    today = '2024_Rocket_Launch'
    data_folder = os.path.join('.', today)
    aux_functions_web.mkdir(data_folder)
    

    # AR parameters, top three first, then bottom three

    label_top=["A", "B", "C"]

    arnum_top=[1,3639, 3635]# active region numbers

    lat_top=[10,30,20]# active region latitude in degrees

    long_top=[-75,-35,30]# active region longitude in degrees

    #These positions are for the southern region

    label_bottom=["D", "E", "F"]

    arnum_bottom=[3649,3637,3634]# active region numbers

    lat_bottom=[-8, -15, -30]# active region latitude in degrees

    long_bottom=[-70, -10, 50]# active region longitude in degrees

    
    label=label_top+label_bottom
    arnum=arnum_top+arnum_bottom
    ar_lat=lat_top+lat_bottom
    ar_lon=long_top+long_bottom
       
    #     arnum  = [3624, 3626, 3622, 1, 0, 3620]
    # ar_lat = [15, 11, 11, -15, +15, -8] #North and South
    # ar_lon = [-30, 33, 53, -15, -55, 66] #West and East 
    # #If boxes are not used, move to ~,80
    
    
    # Duratin of the current session of the data stream
    #duration_stream = 10 # minutes

    # Timezone with respect to which the times are expressed in the plots
    timezone='US/Central'#'US/Mountain'#'US/Alaska'
    
    # Boolean: if True, the fits files of the downloaded AIA maps and of the EM maps that are computed from the AIA data are saved.
    save_maps=False
    
    # Read correction table
    correction_table = get_correction_table(correction_table=os.path.join(".","tables","aia_V10_20201119_190000_response_table.txt"))
    
    # Start AIA data stream
    aux_functions_web.stream_aia_data(data_folder, ar_lon, ar_lat, arnum, label, correction_table, timezone=timezone,save_maps=save_maps)