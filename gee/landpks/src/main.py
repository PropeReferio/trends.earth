# Copyright 2017 Conservation International

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import re
import json
import datetime as dt
import random
import json
import requests
import tempfile
import hashlib
import pathlib
from concurrent.futures import ThreadPoolExecutor, as_completed

import ee
from google.cloud import storage

# Turn off overly informative debug messages
import logging
mpl_logger = logging.getLogger('matplotlib')
mpl_logger.setLevel(logging.WARNING)
pil_logger = logging.getLogger('PIL.PngImagePlugin')
pil_logger.setLevel(logging.WARNING)

from PIL import Image

import numpy as np

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.colors as colors
from matplotlib_scalebar.scalebar import ScaleBar

import pandas as pd

from landdegradation.schemas.schemas import Url, ImageryPNG, \
        ImageryPNGSchema


# Bucket where results will be uploaded (should be publicly readable)
BUCKET = 'ldmt'
# Bounding box side in meters
BOX_SIDE = 5000

class InvalidParameter(Exception):
    pass

def upload_to_google_cloud(client, f):
    b = client.get_bucket(BUCKET)
    blob = b.blob(os.path.basename(f))
    blob.upload_from_filename(f)
    return 'https://storage.googleapis.com/{}/{}'.format(BUCKET, os.path.basename(f))


def get_hash(filename):
    with open(filename, 'rb') as f:
       return hashlib.md5(f.read()).hexdigest()


# Dictionary to remap from ESA CCI to 7 classes - used for landtrend_plot
remap_dict = {'0': '0',
              '50': '1',
              '60': '1',
              '61': '1',
              '62': '1',
              '70': '1',
              '71': '1',
              '72': '1',
              '80': '1',
              '81': '1',
              '82': '1',
              '90': '1',
              '100': '1',
              '160': '1',
              '170': '4',
              '110': '2',
              '120': '2',
              '121': '2',
              '122': '2',
              '130': '2',
              '140': '2',
              '150': '2',
              '151': '2',
              '152': '2',
              '153': '2',
              '40': '2',
              '10': '3',
              '11': '3',
              '12': '3',
              '20': '3',
              '30': '3',
              '180': '4',
              '190': '5',
              '200': '6',
              '201': '6',
              '202': '6',
              '220': '6',
              '210': '7'}

remap_dict = {0: 0,
              50: 1,
              60: 1,
              61: 1,
              62: 1,
              70: 1,
              71: 1,
              72: 1,
              80: 1,
              81: 1,
              82: 1,
              90: 1,
              100: 1,
              160: 1,
              170: 4,
              110: 2,
              120: 2,
              121: 2,
              122: 2,
              130: 2,
              140: 2,
              150: 2,
              151: 2,
              152: 2,
              153: 2,
              40: 2,
              10: 3,
              11: 3,
              12: 3,
              20: 3,
              30: 3,
              180: 4,
              190: 5,
              200: 6,
              201: 6,
              202: 6,
              220: 6,
              210: 7}

# Class names and color codes
classes = pd.DataFrame(data={'Label': ["No data", "Forest", "Grassland", "Cropland",
                                       "Wetland", "Artificial", "Bare", "Water"],
                             'Code' : [0, 1, 2, 3, 4, 5, 6, 7],
                             'Color' : ["#000000", "#787F1B", "#FFAC42", "#FFFB6E",
                                        "#00DB84", "#E60017", "#FFF3D7", "#0053C4"]})

te_logo = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                                 'trends_earth_logo_bl_print.png'))

def plot_image_to_file(d, title, cmap=None, legend=None):
    # find the position to place the dot
    dot_pos = len(d[0])/2
    fig = plt.figure(constrained_layout=False, figsize=(15, 11.28), dpi=100)
    ax = fig.add_subplot()
    ax.set_title(title, {'fontsize' :28})
    ax.set_axis_off()
    plt.plot(dot_pos, dot_pos, 'ko')
    img = ax.imshow(d)
    scalebar = ScaleBar(30, fixed_units ='km', location = 3, box_color = 'none') # 1 pixel = 0.2 meter
    plt.gca().add_artist(scalebar)

    ax_img = fig.add_axes([0.16, 0.73, 0.21, 0.2], anchor='NW')
    if cmap:
        ax_img.imshow(te_logo, cmap=cmap)
    else:
        ax_img.imshow(te_logo)
    ax_img.axis('off')

    if legend:
        ax_legend = fig.add_axes([0.63, 0.07, 0.21, 0.2], anchor='SE')
        ax_legend.imshow(legend)
        ax_legend.axis('off')

    plt.tight_layout()
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    plt.savefig(f, bbox_inches='tight')

    return f


###############################################################################
# Code for landtrendplot

def landtrend_get_data(year_start, year_end, geojson):
    # geospatial datasets 
    lcover = "users/geflanddegradation/toolbox_datasets/lcov_esacc_1992_2018"
    vegindex = "users/geflanddegradation/toolbox_datasets/ndvi_modis_2001_2019"
    precip = "users/geflanddegradation/toolbox_datasets/prec_chirps_1981_2019"
    
    region = ee.Geometry(geojson)

    # sets time series of interest
    lcov = ee.Image(lcover).select(ee.List.sequence(year_start - 1992, 26, 1))    
    ndvi = ee.Image(vegindex).select(ee.List.sequence(year_start - 2001, year_end - 2001, 1))
    prec = ee.Image(precip).select(ee.List.sequence(year_start - 1981, year_end - 1981, 1))

    # retrieves value of the pixel that intesects coord_point
    values_lcov = lcov.reduceRegion(ee.Reducer.toList(), region, 1)
    values_ndvi = ndvi.reduceRegion(ee.Reducer.toList(), region, 1)
    values_prec = prec.reduceRegion(ee.Reducer.toList(), region, 1)

    with ThreadPoolExecutor(max_workers=4) as executor:
        res = []
        for b, img in [('land_cover', values_lcov),
                       ('ndvi', values_ndvi),
                       ('precipitation', values_prec)]:
            res.append(executor.submit((lambda b, img: {b: img.getInfo()}), b, img))
        out = {}
        for this_res in as_completed(res):
            out.update(this_res.result())

    ts = []
    for key in out.keys():   
        d = list((int(k.replace('y', '')), int(v[0])) for k, v in out[key].items())
        # Ensure the data is chronological
        d = sorted(d, key=lambda x: x[0]) 
        years = list(x[0] for x in d)
        data = list(x[1] for x in d)
        ts.append(pd.DataFrame(data={key: data}, index=years))
    
    # Join all the timeseries pandas dataframes together
    out = ts[0]
    for this_ts in ts[1:]:
        out = out.join(this_ts, how='outer')
    
    # Recode the ESA codes to IPCC 7 classes
    for n in range(len(out.index)):
        esa_code = out.land_cover.iloc[n]
        if not np.isnan(esa_code):
            out.land_cover.iloc[n] = remap_dict[esa_code]
        
    return out

def landtrend_make_plot(d, year_start, year_end):
    # Make plot
    fig = plt.figure(constrained_layout=False, figsize=(15, 11.28), dpi=100)
    spec = gridspec.GridSpec(ncols=1, nrows=3, figure=fig,
                             height_ratios=[3, 3, 1], hspace=0)

    axs = []
    for row in range(3):
        axs.append(fig.add_subplot(spec[row, 0]))

    # Account for scaling on NDVI
    d.ndvi = d.ndvi / 10000

    axs[0].plot(d.index, d.ndvi, color='#0B6623', linewidth=3)
    axs[0].set_xlim(year_start, year_end)
    axs[0].set_ylim(d.ndvi.min() * .95, d.ndvi.max() * 1.1)
    axs[0].set_ylabel('NDVI\n(annual)', fontsize=32)
    axs[0].tick_params(axis='y', left=False, right=True, labelleft=False, labelright=True, labelsize=28)
    axs[0].tick_params(axis='x', bottom=False, labelbottom=False)

    axs[1].plot(d.index, d.precipitation, color='#1167b1', linewidth=3)
    axs[1].set_xlim(year_start, year_end)
    axs[1].set_ylabel('Precipitation\n(annual, mm)', fontsize=32)
    axs[1].tick_params(axis='y', left=False, right=True, labelleft=False, labelright=True, labelsize=28)
    axs[1].tick_params(axis='x', bottom=False, labelbottom=False)

    pd.options.mode.chained_assignment = None  # default='warn'
    for n in range(len(d.index)):
        if not np.isnan(d.land_cover.iloc[n]):
            axs[2].fill_between([d.index[n], d.index[n] + 1],
                                [0, 0], [1, 1],
                                color=classes.Color.iloc[int(d.land_cover.iloc[n])],
                                label=classes.Label.iloc[int(d.land_cover.iloc[n])])
    axs[2].set_xlim(year_start, year_end)
    axs[2].set_ylim(0, 5)
    axs[2].tick_params(axis='y', left=False, labelleft=False, labelsize=28)
    axs[2].tick_params(axis='x', labelsize=28)
    axs[2].set_xlabel('Year', fontsize=32)
    axs[2].set_ylabel('Land\nCover', fontsize=32)
    handles, labels = axs[2].get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    axs[2].legend(by_label.values(), by_label.keys(), ncol=4, frameon=False, fontsize=26, borderpad=0)

    height = te_logo.size[1]
    # We need a float array between 0-1, rather than
    # a uint8 array between 0-255
    im_array = np.array(te_logo).astype(np.float) / 255
    fig.figimage(im_array, 120, fig.bbox.ymax - height - 40, zorder=-1)
    
    # Set the first axis background to transparent so the trends.earth logo (placed behind it) will show through
    axs[0].patch.set_facecolor('w')
    axs[0].patch.set_alpha(0)
    
    return plt


def landtrend(year_start, year_end, geojson, lang, gc_client):
    res = landtrend_get_data(year_start, year_end, geojson)
    plt = landtrend_make_plot(res, year_start, year_end)

    plt.tight_layout()
    f = tempfile.NamedTemporaryFile(suffix='.png').name
    plt.savefig(f, bbox_inches='tight')
    h = get_hash(f)

    url = Url(upload_to_google_cloud(gc_client, f), h)

    #TODO: Need to return date as a period
    out = ImageryPNG(name='landtrend_plot',
                     lang=lang,
                     title='This is a title',
                     date=[dt.date(year_start, 1, 1), dt.date(year_end, 12, 31)],
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'landtrend_plot' : schema.dump(out)}


###############################################################################
# Code for base image (Landsat 8 RGB plot)

# Function to mask out clouds and cloud-shadows present in Landsat images
def maskL8sr(image):
    # Bits 3 and 5 are cloud shadow and cloud, respectively.
    cloudShadowBitMask = (1 << 3)
    cloudsBitMask = (1 << 5)
    # Get the pixel QA band.
    qa = image.select('pixel_qa')
    # Both flags should be set to zero, indicating clear conditions.
    mask = qa.bitwiseAnd(cloudShadowBitMask).eq(0)
    mask = qa.bitwiseAnd(cloudsBitMask).eq(0)

    return image.updateMask(mask)

# Function to generate the Normalized Diference Vegetation Index, NDVI = (NIR + 
# Red)/(NIR + Red) 
def calculate_ndvi(image):
    return image.normalizedDifference(['B5', 'B4']).rename('NDVI')

def get_band(img, b):
    # Get 2-d pixel array for AOI property per band, transfer the arrays from 
    # server to client, cast as np array, and expand the dimensions of the 
    # images so they can later be concatenated into 3-D.
    band = np.expand_dims(np.array(img.get('B3').getInfo()), 2)
    return {b: band}

OLI_SR_COLL = ee.ImageCollection('LANDSAT/LC08/C01/T1_SR')
def base_image(year, geojson, lang, gc_client):
    start_date = dt.datetime(year, 1, 1)
    end_date = dt.datetime(year, 12, 31)
    region = ee.Geometry(geojson).buffer(BOX_SIDE / 2).bounds()

    # Mask out clouds and cloud-shadows in the Landsat image
    range_coll = OLI_SR_COLL.filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'))
    l8sr_y = (range_coll.map(maskL8sr).median().setDefaultProjection(range_coll.first().projection()))

    # Reproject L8 image so it can be correctly passed to 'sampleRectangle()' 
    # function
    l8sr_mosaic_bands = l8sr_y.reproject(scale=30, crs='EPSG:3857') \
        .select(['B2', 'B3', 'B4']) \
        .sampleRectangle(region)

    with ThreadPoolExecutor(max_workers=4) as executor:
        res = []
        for b in ['B4', 'B3', 'B2']:
            res.append(executor.submit(get_band, l8sr_mosaic_bands, b))
        # Gather results and concatenate them
        out = {}
        for this_res in as_completed(res):
            out.update(this_res.result())
        rgb_img = np.concatenate((out['B4'], out['B3'], out['B2']), 2)
    
    # get the image max value
    img_max = np.max(rgb_img)
    
    # Scale the data to [0, 255] to show as an RGB image.
    rgb_img_plot = (255*((rgb_img - 100)/img_max)).astype('uint8')

    f = plot_image_to_file(rgb_img_plot, "Satellite Image")

    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    out = ImageryPNG(name='base_image',
                     lang=lang,
                     title='This is a title',
                     date=[start_date, end_date],
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'base_image' : schema.dump(out)}


###############################################################################
# Greenness average

def greenness(year, geojson, lang, gc_client):
    start_date = dt.datetime(year, 1, 1)
    end_date = dt.datetime(year, 12, 31)
    region = ee.Geometry(geojson).buffer(BOX_SIDE / 2).bounds()
    ndvi_mean = OLI_SR_COLL.filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
            .map(maskL8sr) \
            .map(calculate_ndvi) \
            .mean() \
            .addBands(ee.Image(year).float()) \
            .rename(['ndvi','year'])

    # Reproject ndvi_mean and ndvi_trnd images so they can be correctly passed 
    # to 'sampleRectangle()' function
    ndvi_mean_reproject = ndvi_mean.reproject(scale=30, crs='EPSG:3857')
    ndvi_mean_band = ndvi_mean_reproject.select('ndvi').sampleRectangle(region)
    ndvi_arr_mean = np.array(ndvi_mean_band.get('ndvi').getInfo())

    legend = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                                    'ndvi_avg_{}.png'.format(lang.lower())))
    f = plot_image_to_file(ndvi_arr_mean, 'Average Greenness', 'Greens', legend)

    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    out = ImageryPNG(name='greenness',
                     lang=lang,
                     title='This is a title',
                     date=[start_date, end_date],
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness' : schema.dump(out)}


###############################################################################
# Greenness trend

def greenness_trend(year_start, year_end, geojson, lang, gc_client):
    start_date = dt.datetime(year_start, 1, 1)
    end_date = dt.datetime(year_end, 12, 31)
    region = ee.Geometry(geojson).buffer(BOX_SIDE / 2).bounds()
    ndvi = []
    for y in range(year_start, year_end + 1):
        ndvi.append(OLI_SR_COLL \
                        .filterDate(start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d')) \
                        .map(maskL8sr) \
                        .map(calculate_ndvi) \
                        .mean() \
                        .addBands(ee.Image(y).float()) \
                        .rename(['ndvi','year']))
    ndvi_coll = ee.ImageCollection(ndvi)

    # Compute linear trend function to predict ndvi based on year (ndvi trend)
    lf_trend = ndvi_coll.select(['year', 'ndvi']).reduce(ee.Reducer.linearFit())
    ndvi_trnd = (lf_trend.select('scale').divide(ndvi[0].select("ndvi"))).multiply(100)
    # Reproject ndvi_mean and ndvi_trnd images so they can be correctly passed to 'sampleRectangle()' function
    ndvi_trnd_reproject= ndvi_trnd.reproject(scale=30, crs='EPSG:3857')
    ndvi_trnd_band = ndvi_trnd_reproject.select('scale').sampleRectangle(region)
    # Get individual band arrays.
    ndvi_arr_trnd = ndvi_trnd_band.get('scale')
    # Transfer the arrays from server to client and cast as np array.
    ndvi_arr_trnd = np.array(ndvi_arr_trnd.getInfo()).astype('float64')

    legend = Image.open(os.path.join(pathlib.Path(__file__).parent.absolute(), 
                                 'ndvi_trd_{}.png'.format(lang.lower())))
    f = plot_image_to_file(ndvi_arr_trnd, 'Greenness Trend', 'PiYG', legend)

    h = get_hash(f)
    url = Url(upload_to_google_cloud(gc_client, f), h)

    out = ImageryPNG(name='greenness_trend',
                     lang=lang,
                     title='This is a title',
                     date=[start_date, end_date],
                     about="This is some about text, with a link in it to the <a href='http://trends.earth'>Trends.Earth</a> web page.",
                     url=url)
    schema = ImageryPNGSchema()
    return {'greenness_trend' : schema.dump(out)}


###############################################################################
# Main

def run(params, logger):
    """."""
    logger.debug("Loading parameters.")
    year_start = int(params.get('year_start', None))
    if year_start < 2001:
        raise InvalidParameter("Invalid starting year {}".format(year_start))
    year_end = int(params.get('year_end', None))
    lang = params.get('lang', None)
    langs =['EN', 'ES', 'PT']
    if lang not in langs:
        logger.debug("Unknown language {}, returning EN".format(lang))
        lang = 'EN'
    geojson = json.loads(params.get('geojson', None))
    if not geojson['type'].lower() == 'point':
        raise InvalidParameter('geojson must be of type "Point"')
    # Check the ENV. Are we running this locally or in prod?
    if params.get('ENV') == 'dev':
        EXECUTION_ID = str(random.randint(1000000, 99999999))
    else:
        EXECUTION_ID = params.get('EXECUTION_ID', None)

    logger.debug('Authenticating with AWS...')
    gc_client = storage.Client()
    logger.debug('Authenticated with AWS.')

    logger.debug("Running main script.")
    threads = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        logger.debug("Starting threads...")
        res = []
        res.append(executor.submit(landtrend, year_start, year_end, 
            geojson, lang, gc_client))
        res.append(executor.submit(base_image, year_end, geojson, lang, 
            gc_client))
        res.append(executor.submit(greenness, year_end, geojson, lang, 
            gc_client))
        res.append(executor.submit(greenness_trend, year_end - 5, year_end, 
            geojson, lang, gc_client))
        out = {}
        logger.debug("Gathering thread results...")
        for future in as_completed(res):
            out.update(future.result())
        return(out)
