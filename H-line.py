import os
import sys
import json
import argparse
import contextlib
from time import sleep
from datetime import datetime, timedelta

# Due to Receive.py not wanting to be importet we add src to path
sys.path.append("src/")
from Rtltcp import RTLTCP
from Receive import Receiver
from Plot import Plot
from Ephem import Coordinates


# Reads user parameters
def parser():
    parser = argparse.ArgumentParser(
        prog = 'H-line-observer',
        description = 'An interface to receive H-line data'
    )

    # Parsing options (receiver)
    parser.add_argument('-s', metavar = 'Sample rate', type = int, help = 'Tuner sample rate', default = 2400000, dest = 'sample_rate')
    parser.add_argument('-o', metavar = 'PPM offset', type = int, help = 'Set custom tuner offset PPM', default = 0, dest = 'ppm')
    parser.add_argument('-r', metavar = 'Resolution', type = int, help = 'Amount of samples = 2 raised to the power of the input', default = 11, dest = 'resolution')
    parser.add_argument('-n', metavar = 'Number of FFT\'s', type = int, help = 'Number of FFT\'s to be collected and averaged', default = 1000, dest = 'num_FFT')
    parser.add_argument('-i', metavar = 'Degree interval', type = float, help = 'Degree interval of each data-collection. Collects data for 24h.', default = 0.0, dest = 'interval')
    parser.add_argument('-m', metavar = 'Median smoothing', type = int, help = 'Number of data-points to compute median from. Smooths data and compresses noise', default = 3, dest = 'num_med')
    parser.add_argument('-t', help = 'Run RTL-TCP host for streaming to client', action = 'store_true', dest = 'host')
    parser.add_argument('-e', metavar = 'RTL-TCP streaming', type = str, help = 'Stream from IP of remote server. This command is used for client side.', default = 'none', dest = 'remote_ip')
    parser.add_argument('-d', help = 'Debug data', action = 'store_true', dest = 'debug')

    # Parsing options (observer)
    parser.add_argument('-l', metavar = 'Latitude', type = float, help = 'The latitude of the antenna\'s position as a float, north is positive', default = 0.0, dest = 'latitude')
    parser.add_argument('-g', metavar = 'Longitude', type = float, help = 'The longitude of the antenna\'s position as a float, east is positive', default = 0.0, dest = 'longitude')
    parser.add_argument('-z', metavar = 'Azimuth', type = float, help = 'The azimuth of the poting direction', default = 0.0, dest = 'azimuth')
    parser.add_argument('-a', metavar = 'Altitude', type = float, help = 'The elevation of the pointing direction', default = 0.0, dest = 'altitude')
    parser.add_argument('-c', help = 'Use lat, lon of QTH and antenna alt/az from config file', action = 'store_true', dest = 'use_config')
    parser.set_defaults(use_config = False)
    
    args = parser.parse_args()

    main(args)


# Main method
def main(args):

    # Does user want this device to act as RTL-TCP host? If yes - start host
    if args.host:
        TCP_class = RTLTCP(sample_rate = args.sample_rate, ppm = args.ppm, resolution = args.resolution, num_FFT = args.num_FFT, num_med = args.num_med)
        TCP_class.rtltcphost()
        quit()

    # Get current observer location and antenna pointing direction
    if args.use_config:
        config = read_config()
        lat, lon = config['latitude'], config['longitude']
        alt, az = config['altitude'], config['azimuth']

        # Get y-axis limits from config
        low_y, high_y = config['low_y'], config['high_y']
        if "none" in (lat, lon, alt, az):
            print('Please check your config file or use command line arguments.')
            quit()
    else:
        low_y, high_y = 'none', 'none'
        lat, lon = args.latitude, args.longitude
        alt, az = args.altitude, args.azimuth

    # Checks if 360 is divisable with the degree interval and calculates number of collections
    num_data = 360/args.interval if args.interval != 0 else 0
    second_interval = 24*60**2/num_data if num_data > 0 else None

    if float(num_data).is_integer():
        # Set coordinates for each observation if possible
        if 0.0 == lat == lon == alt == az:
            ra, dec = 'none', 'none'
            observer_velocity = 'N/A'
        else:
            # Get current equatorial and galactic coordinates of antenna RA and Declination
            Coordinates_class = Coordinates(lat = lat, lon = lon, alt = alt, az = az)
            ra, dec = Coordinates_class.equatorial(num_data, args.interval)
            gal_lat, gal_lon = Coordinates_class.galactic()
            observer_velocity = Coordinates_class.observer_velocity(gal_lat, gal_lon)
        
        # Current time of first data collection
        current_time = datetime.utcnow()
        num_data = int(num_data)
        
        # Check if one or multiple observations are planned
        if num_data == 0:
            # Perform only ONE observation
            freqs, data = observe(args)
            if args.debug:
                write_debug(freqs, data, args, ra, dec)
            plot(freqs, data, ra, dec, low_y, high_y, observer_velocity)
        else:
            # Perform multiple observations for 24 hours
            for i in range (num_data):
                freqs, data = observe(args)
                plot(freqs, data, ra[i], dec, low_y, high_y, observer_velocity)

                # Wait for next execution
                clear_console()
                end_time = current_time + timedelta(seconds = second_interval * (i + 1))
                time_remaining = end_time - datetime.utcnow()
                print(f'Waiting for next data collection in {time_remaining.total_seconds()} seconds')
                sleep(time_remaining.total_seconds())
            
            # Generate GIF from observations
            Plot_class = Plot(freqs = freqs, data = data, observer_velocity = observer_velocity)
            Plot_class.generate_GIF(ra[0], dec)
            
    else:
        print('360 must be divisable with the degree interval. Eg. the quotient must be a positive natural number (1, 2, 3, and not 3.4)')
        quit()


# Performs observation
def observe(args):
    # Receives and writes data - either through RTLTCP or locally
    print(f'Receiving {args.num_FFT} bins of {2 ** args.resolution} samples each...')
    
    # Disable console printouts due to pyrtlsdr printing repeating message when using RTL-TCP
    with contextlib.redirect_stdout(None):
        if args.remote_ip != 'none':
            TCP_class = RTLTCP(sample_rate = args.sample_rate, ppm = args.ppm, resolution = args.resolution, num_FFT = args.num_FFT, num_med = args.num_med)
            return TCP_class.rtltcpclient(args.remote_ip)
        else:
            Receiver_class = Receiver(TCP = False, client = 0, sample_rate = args.sample_rate, ppm = args.ppm, resolution = args.resolution, num_FFT = args.num_FFT, num_med = args.num_med)
            return Receiver_class.receive()


# Plots data
def plot(freqs, data, ra, dec, low_y, high_y, observer_velocity):
    print('Plotting data...')
    Plot_class = Plot(freqs = freqs, data = data, observer_velocity = observer_velocity)
    Plot_class.plot(ra = ra, dec = dec, low_y = low_y, high_y = high_y)

# Write debug file
# TODO Add raw data in this file as well
def write_debug(freqs, data, args, ra, dec):
    parameters = {
        "sample_rate": args.sample_rate,
        "ppm": args.ppm,
        "resolution": args.resolution,
        "num_FFT": args.num_FFT,
        "num_med": args.num_med
    }
    if not isinstance(data, list):
        data = data.tolist()
    data = {
        "Freqs": freqs.tolist(),
        "Data": data
    }
    json_file = {"Parameters": parameters, "Data": data}

    if "none" in (ra, dec):
        stamp = datetime.utcnow().strftime('D%m%d%YT%H%M%S')
    else:
        stamp = f'ra={ra},dec={dec}'

    with open(f"Spectrums/debug({stamp}).json", "w") as file:
        json.dump(json_file, file, indent = 4)

# Reads the config file and returns JSON graph
def read_config():
    path = 'config.json'
    config = open(path, 'r')
    parsed_config = json.load(config)
    return parsed_config

def clear_console():
    os.system('cls' if os.name =='nt' else 'clear')

if __name__ == "__main__":
    parser()
