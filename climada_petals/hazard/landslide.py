"""
This file is part of CLIMADA.

Copyright (C) 2017 ETH Zurich, CLIMADA contributors listed in AUTHORS.

CLIMADA is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free
Software Foundation, version 3.

CLIMADA is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along
with CLIMADA. If not, see <https://www.gnu.org/licenses/>.

---

Define Landslide class.
"""

__all__ = ['Landslide']

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.stats import binom, poisson
import shapely

from climada.hazard import Hazard, Centroids
import climada.util.coordinates as u_coord
from climada.util.constants import DEF_CRS

LOGGER = logging.getLogger(__name__)
HAZ_TYPE = 'LS'


def sample_events(prob_matrix, n_years, dist='binom'):
    """Repeatedly sample events"""
    events = [
        sample_event_from_probs(prob_matrix, n_years=1, dist=dist)
        for i in range(n_years)
        ]
    return sparse.csr_matrix(events)
    
    
def sample_event_from_probs(prob_matrix, n_years, dist):
    """sample an event  for a specified representative time span from
    a matrix with occurrence probabilities. Draws events from chosen 
    distribution.

    Parameters
    ----------
    prob_matrix : np.array()
        matrix where each entry has a probability [0,1] of occurrence of
        an event
    n_years : int
        the timespan of the probabilistic simulation in years. default is 1.
    dist : str
        distribution to sample from. currently 'binom' (default) and 'poisson'

    Returns
    -------
    ev_matrix : np.array()
        array of same shape as prob_matrix with number of 'hits' from sampling
        per entry

    See also
    --------
    set_ls_prob(), scipy.stats.binom.rvs(), scipy.stats.poisson.rvs()

    """
    if dist == 'binom':
        ev_matrix = binom.rvs(n=n_years, p=prob_matrix)

    elif dist == 'poisson':
        # λ (or μ in scipy)
        mu = prob_matrix * n_years
        ev_matrix = poisson.rvs(mu)

    return ev_matrix


class Landslide(Hazard):
    """Landslide Hazard set generation."""

    def __init__(self):
        """Empty constructor."""
        Hazard.__init__(self, HAZ_TYPE)

    @classmethod
    def from_hist(cls, bbox, input_gdf, res=0.0083333):
        """
        Set historic landslide (ls) raster hazard from historical point records,
        for example as can be retrieved from the NASA COOLR initiative,
        which is the largest global ls repository, for a specific geographic
        extent.
        Points are assigned to the gridcell they fall into, and the whole grid-
        cell hence counts as equally affected.
        Event frequencies from an incomplete dataset are not meaningful and
        hence aren't set by default. probabilistic calculations!
        Use the probabilistic method for this!

        See tutorial for details; the global ls catalog from NASA COOLR can bedownloaded from
        https://maps.nccs.nasa.gov/arcgis/apps/webappviewer/index.html?id=824ea5864ec8423fb985b33ee6bc05b7

        Note
        -----
        The grid which is generated has the same projection as the geodataframe
        with point occurrences. By default, this is EPSG:4326, which is a non-
        projected, geographic CRS. This means, depending on where on the globe
        the analysis is performed, the area per gridcell differs vastly.
        Consider this when setting your resoluton (e.g. at the equator,
        1° ~ 111 km). In turn, one can use projected CRS which preserve angles
        and areas within the reference area for which they are defined. To do
        this, reproject the input_gdf to the desired projection.
        For more on projected & geographic CRS, see
        https://desktop.arcgis.com/en/arcmap/10.3/guide-books/map-projections/about-projected-coordinate-systems.htm

        Parameters
        ----------
        bbox : tuple
            (minx, miny, maxx, maxy) geographic extent of interest
        input_gdf : str or  or geopandas geodataframe
             path to shapefile (.shp) with ls point data or already laoded gdf
        res : float
            resolution in units of the input_gdf crs of the final grid cells
            which are created. Whith EPSG:4326, this is degrees. Default is
            0.008333.

        Returns
        -------
        Landslide : Landslide
            instance filled with historic LS hazard
            set for either point hazards or polygons with specified
            surrounding extent.
        """
        haz = cls()
        if isinstance(input_gdf, gpd.GeoDataFrame):
            LOGGER.info('Using pre-loaded gdf')
            gdf_cropped = input_gdf.copy().cx[bbox[0]:bbox[2], bbox[1]:bbox[3]]
        else:
            LOGGER.info('Reading in gdf from source %s', input_gdf)
            gdf_cropped = gpd.read_file(input_gdf, bbox=bbox)

        LOGGER.info('Generating a raster with resolution %s for box %s', res, bbox)
        if not gdf_cropped.crs:
            gdf_cropped.crs = DEF_CRS
        haz.centroids = Centroids.from_pnt_bounds(bbox, res, crs=gdf_cropped.crs)

        n_ev = len(gdf_cropped)

        # assign lat-lon points of LS events to corresponding grid & flattened
        # grid-index
        grid_height, grid_width, grid_transform = u_coord.pts_to_raster_meta(bbox, (res, -res))
        gdf_cropped['flat_ix'] = u_coord.assign_grid_points(
            gdf_cropped.geometry.x, gdf_cropped.geometry.y,
            grid_width, grid_height, grid_transform)
        haz.intensity = sparse.csr_matrix(
            (np.ones(n_ev), (np.arange(n_ev), gdf_cropped.flat_ix)),
            shape=(n_ev, haz.centroids.size))
        haz.fraction = haz.intensity.copy()

        if hasattr(gdf_cropped, 'ev_date'):
            haz.date = pd.to_datetime(gdf_cropped.ev_date, yearfirst=True)
        else:
            LOGGER.info('No event dates set from source')

        if haz.date.size > 0:
            haz.frequency = np.ones(n_ev)/(
                (haz.date.max()-haz.date.min()).value/3.154e+16)
        else:
            LOGGER.warning('no event dates to derive proxy frequency from,'+ 
                           'setting arbitrarily to once per year.')
            haz.frequency = np.ones(n_ev)

        haz.units = ''
        haz.event_id = np.arange(n_ev, dtype=int) + 1
        haz.orig = np.ones(n_ev, bool)

        haz.check()
        
        return haz

    def set_ls_hist(self, *args, **kwargs):
        """
        This function is deprecated, use Landslide.from_hist instead.
        """
        """"""
        LOGGER.warning("The use of Landlide.set_ls_hist is deprecated."
                       "Use Landslide.from_hist instead")
        self.__dict__ = Landslide.from_hist(*args, **kwargs).__dict__

    @classmethod
    def from_prob(cls, bbox, path_sourcefile, corr_fact=10e6, n_years=500,
                    dist='poisson'):
        """
        Set probabilistic landslide hazard (fraction, intensity and
        frequency) for a defined bounding box and time period from a raster.
        The hazard data for which this function is explicitly written
        is readily provided by UNEP & the Norwegian Geotechnical Institute
        (NGI), and can be downloaded and unzipped from
        https://preview.grid.unep.ch/index.php?preview=data&events=landslides&evcat=2&lang=eng
        for precipitation-triggered landslide and from
        https://preview.grid.unep.ch/index.php?preview=data&events=landslides&evcat=1&lang=eng
        for earthquake-triggered landslides.
        It works with any similar raster file.
        Original data is given in expected annual probability and percentage
        of pixel of occurrence of a potentially destructive landslide event
        x 1000000 (so be sure to adjust this by setting the correction factor).
        More details can be found in the landslide tutorial and under above-
        mentioned links.

        Events are sampled from annual occurrence probabilites via binomial or
        poisson distribution. An event therefore includes all landslides
        sampled to occur within a year for the given area.
        intensity takes a binary value (occurrence or no occurrene of a LS);
        frequency is set to 1 / n_years.
        

        Impact functions, since they act on the intensity, should hence be in
        the form of a step function,
        defining impact for intensity 0 and (close to) 1.

        Parameters
        ----------
        bbox : tuple
            (minx, miny, maxx, maxy) geographic extent of interest
        path_sourcefile : str
            path to UNEP/NGI ls hazard file (.tif)
        corr_fact : float or int
            factor by which to divide the values in the original probability
            file, in case it is not scaled to [0,1]. Default is 1'000'000
        n_years : int
            sampling period
        dist : str
            distribution to sample from. 'poisson' (default) and 'binom'

        Returns
        -------
        haz : climada.hazard.Landslide instance
            probabilistic LS hazard

        See also
        --------
        sample_events()
        sample_event_from_probs()
        """
        
        haz = cls()
        # raster with occurrence probs
        haz.centroids.meta, prob_matrix = \
            u_coord.read_raster(path_sourcefile, geometry=[shapely.geometry.box(*bbox, ccw=True)])
        prob_matrix = prob_matrix.squeeze()/corr_fact

        # sample events from probabilities
        haz.intensity = sample_events(prob_matrix, n_years, dist)
        haz.fraction = haz.intensity.copy()
        haz.fraction[haz.intensity.nonzero()] = 1
        haz.frequency = np.ones(n_years) / n_years

        # meaningless, such that check() method passes:
        haz.date = np.array([])
        haz.event_name = np.array(range(n_years))
        haz.event_id = np.array(range(n_years))

        if not haz.centroids.meta['crs'].is_epsg_code:
            haz.centroids.meta['crs'] = haz.centroids.meta['crs'
                               ].from_user_input(DEF_CRS)
        haz.centroids.set_geometry_points()
        
        haz.check()
        
        return haz
        
    def set_ls_prob(self, *args, **kwargs):
        """
        This function is deprecated, use Landslide.from_prob instead.
        """
        """"""
        LOGGER.warning("The use of Landlide.set_ls_prob is deprecated."
                       "Use Landslide.from_prob instead")
        self.__dict__ = Landslide.from_prob(*args, **kwargs).__dict__
        