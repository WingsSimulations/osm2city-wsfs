# SPDX-FileCopyrightText: (C) 2020, rick@vanosten.net
# SPDX-License-Identifier: GPL-2.0-or-later
"""
Module to query data on the internet using JSON.

from WikiData


"""
import base64
import io
import json
import logging
import os
from os import path
import time
from typing import Optional
import zipfile

import requests


def _json_query_status(url: str, context: str) -> Optional[requests.Response]:
    # This method is often called in a loop.
    # Currently, there is a limit of 60 requests to e.g. WikiData -> throttle
    # See https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#Query_limits
    time.sleep(1.0)
    status_code = -1
    try:
        r = requests.get(url=url, timeout=1.)
        status_code = r.status_code
        r.raise_for_status()
    except ConnectionError:
        logging.warning('Network connection error occurred in fetching data from %s', context)
        return None
    except requests.HTTPError:
        logging.warning('Response error in fetching data from %s: code = %i', context, status_code)
        return None
    except requests.ReadTimeout:
        logging.warning('Read timeout error occurred in fetching data from %s', context)
        return None
    except Exception:  # now we just give up, but want to continue - most probably just no connection
        logging.warning('Some error occurred in fetching data from %s', context)
        return None
    return r


def query_population_wikidata(entity_id: str) -> Optional[int]:
    """Queries WikiData for population data of a given entity.
    Might raise all sorts of exceptions. In any case of problem the return value is None.
    Errors will be logged.

    https://wiki.openstreetmap.org/wiki/Key:wikidata?uselang=en-GB
    https://www.wikidata.org/wiki/Wikidata:SPARQL_query_service/Wikidata_Query_Help
    https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual#SPARQL_endpoint

    E.g. https://www.wikidata.org/wiki/Q1425473

    Population property: https://www.wikidata.org/wiki/Property:P1082

    select * where {
      wd:Q1425473 wdt:P1082 ?o .
      }
    """
    query = 'https://query.wikidata.org/sparql?query=SELECT%20*%20WHERE%20{wd:' + entity_id
    query += '%20wdt:P1082%20?o%20.}&format=json'

    response = _json_query_status(query, 'Wikidata')
    if response is None:
        return None

    try:
        data = json.loads(response.content.decode())
        bindings = data['results']['bindings']
        if bindings:  # the result can also be empty when the place exists but does not have population data
            value_dict = bindings[0]
            return int(value_dict['o']['value'])
        else:
            return None
    except (ValueError, KeyError):
        logging.exception('Error in interpreting data from WikiData with id=%i', entity_id)
        return None


def query_airport_xplane(icao: str) -> Optional[int]:
    """Queries the X-Plane Scenery Gateway for recommended scenery at a specific airport.

    Returns None if error, airport does not exist or does not have a recommended scenery.

    https://gateway.x-plane.com/api#get-a-single-airport
    """
    query = 'https://gateway.x-plane.com/apiv1/airport/{}'.format(icao)
    context = 'X-Plane Scenery Gateway single airport'
    response = _json_query_status(query, context)
    if response is None:
        return None

    try:
        data = json.loads(response.content.decode())
        if 'airport' in data:
            airport_data = data['airport']
            if 'icao' in airport_data and airport_data['icao'] == icao and 'recommendedSceneryId' in airport_data:
                return airport_data['recommendedSceneryId']
        logging.warning('Data structure is not as expected in response for %s', context)
        return None
    except (ValueError, KeyError):
        logging.exception('Error in interpreting data from %s for icao=%s', context, icao)
        return None


def query_scenery_xplane(scenery_id: int, icao: str) -> Optional[str]:
    """Queries the X-Plane Scenery Gateway for a specific scenery pack. Returns file name if there is 3D information.

    Returns None if error.

    We only need the .txt file included in the zip-file, not the .dat file.
    The .txt file gets written to the working directory and renamed to [icao]_[scenery_id].txt. If the file already
    exists, then True is returned and no new data is fetched.

    https://gateway.x-plane.com/api#get-scenery
    """
    scenery_file = '{}_{}.txt'.format(icao, scenery_id)
    if path.exists(scenery_file):
        return scenery_file
    query = 'https://gateway.x-plane.com/apiv1/scenery/{}'.format(scenery_id)
    context = 'X-Plane Scenery Gateway specific scenery'
    response = _json_query_status(query, context)
    if response is None:
        return None

    try:
        data = json.loads(response.content.decode())
        zip_base64 = data["scenery"]["masterZipBlob"]
        response_icao = data['scenery']['icao']
        if icao != response_icao:
            logging.warning('For some reason the ICAO is wrong in %s: returned=%s, expected=%s', context,
                            response_icao, icao)
            return None
        zip_blob = base64.b64decode(zip_base64)

        zip_bytearray = io.BytesIO(zip_blob)
        zip_fhandle = zipfile.ZipFile(zip_bytearray)
        the_file = '{}.txt'.format(icao)
        try:
            _ = zip_fhandle.read(the_file)
        except IOError:
            logging.info('There is no 3D info for icao=%s', icao)
            return None  # just testing whether it exists - sometimes there is only 2D information
        zip_fhandle.extract(the_file)
        os.rename(the_file, scenery_file)
        return scenery_file
    except (ValueError, KeyError, IOError):
        logging.exception('Error in interpreting data from %s for scenery ID=%i and ICAO=%s', context, scenery_id, icao)
        return None


if __name__ == '__main__':
    my_entity_id = 'Q1425473'
    print(query_population_wikidata(my_entity_id))

    my_icao = 'KBOS'
    my_scenery_id = query_airport_xplane(my_icao)
    print(my_scenery_id)

    query_scenery_xplane(my_scenery_id, my_icao)
