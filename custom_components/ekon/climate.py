#!/usr/bin/python
# Do basic imports
import requests
import json
import time
import importlib.util
import socket
import base64
import re
import sys

import asyncio
import logging
import binascii
import os.path
import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant.components.climate import (ClimateEntity, PLATFORM_SCHEMA)

from homeassistant.components.climate.const import (
    HVAC_MODE_OFF, HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_DRY,
    HVAC_MODE_FAN_ONLY, HVAC_MODE_HEAT, SUPPORT_FAN_MODE,
    SUPPORT_TARGET_TEMPERATURE, FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH)

from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT, ATTR_TEMPERATURE, 
    CONF_NAME, CONF_HOST, CONF_PORT, CONF_MAC, CONF_TIMEOUT, CONF_CUSTOMIZE, 
    STATE_ON, STATE_OFF, STATE_UNKNOWN, 
    TEMP_CELSIUS, PRECISION_WHOLE, PRECISION_TENTHS, )

from homeassistant.helpers.event import (async_track_state_change)
from homeassistant.core import callback
from homeassistant.helpers.restore_state import RestoreEntity
from configparser import ConfigParser
from Crypto.Cipher import AES
try: import simplejson
except ImportError: import json as simplejson

REQUIREMENTS = ['']

_LOGGER = logging.getLogger(__name__)

SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE | SUPPORT_FAN_MODE

DEFAULT_NAME = 'EKON Climate'
DEFAULT_BASE_URL = "https://www.airconet.info/"

CONF_USERNAME = 'username'
CONF_PASSWORD = 'password'
CONF_URL_BASE = 'base_url'
DEFAULT_TIMEOUT = 10

# What I recall are the min and max for the HVAC
MIN_TEMP = 16
MAX_TEMP = 30

# fixed values in ekon mode lists
HVAC_MODES = [HVAC_MODE_AUTO, HVAC_MODE_COOL, HVAC_MODE_DRY, HVAC_MODE_FAN_ONLY, HVAC_MODE_HEAT, HVAC_MODE_OFF]

FAN_MODES = [FAN_AUTO, FAN_LOW, FAN_MEDIUM, FAN_HIGH]

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    vol.Optional(CONF_URL_BASE, default=DEFAULT_BASE_URL): cv.string,
    vol.Required(CONF_USERNAME): cv.string,
    vol.Required(CONF_PASSWORD): cv.string,
    vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int
})

EKON_PROP_ONOFF = 'onoff' 
EKON_PROP_MODE = 'mode'
EKON_PROP_FAN = 'fan'
EKON_PROP_ENVIROMENT_TEMP = 'envTemp'
EKON_PROP_TARGET_TEMP = 'tgtTemp'

"""
    public boolean mo3405e() {
        return (this.f2619c == 1 || this.f2619c == 85) ? false : true;
    }
"""
EKON_VALUE_ON = 85
EKON_VALUE_OFF = -86 # or 1 ? or any other value then 85 ?

EKON_VALUE_FAN_LOW = 1
EKON_VALUE_FAN_MEDIUM = 2
EKON_VALUE_FAN_HIGH = 3

"""
                case R.id.mode_auto /*2131230873*/:
                    i = 51;
                    break;
                case R.id.mode_cooling /*2131230875*/:
                    i = 17;
                    break;
                case R.id.mode_dry /*2131230877*/:
                    i = 85;
                    break;
                case R.id.mode_fan /*2131230879*/:
                    i = 68;
                    break;
                case R.id.mode_heating /*2131230881*/:
                    i = 34;
                    break;
"""
EKON_VALUE_MODE_COOL = 17
EKON_VALUE_MODE_AUTO = 51
EKON_VALUE_MODE_DRY = 85
EKON_VALUE_MODE_HEAT = 34
EKON_VALUE_MODE_FAN = 68

# Note that this may not be direct translation, see the sync functions
MAP_MODE_EKON_TO_HASS = {
    EKON_VALUE_MODE_COOL: HVAC_MODE_COOL,
    EKON_VALUE_MODE_AUTO: HVAC_MODE_AUTO,
    EKON_VALUE_MODE_DRY: HVAC_MODE_DRY,
    EKON_VALUE_MODE_HEAT: HVAC_MODE_HEAT,
    EKON_VALUE_MODE_FAN: HVAC_MODE_FAN_ONLY
}

MAP_MODE_HASS_TO_EKON = {
    HVAC_MODE_COOL: EKON_VALUE_MODE_COOL,
    HVAC_MODE_AUTO: EKON_VALUE_MODE_AUTO,
    HVAC_MODE_DRY: EKON_VALUE_MODE_DRY,
    HVAC_MODE_HEAT: EKON_VALUE_MODE_HEAT,
    HVAC_MODE_FAN_ONLY: EKON_VALUE_MODE_FAN
}

"""
                case R.id.fan_auto /*2131230824*/:
                    i = 0;
                    break;
                case R.id.fan_large /*2131230825*/:
                    i = 3;
                    break;
                case R.id.fan_medium /*2131230826*/:
                    i = 2;
                    break;
                case R.id.fan_small /*2131230827*/:
                    i = 1;
                    break;
"""
MAP_FAN_EKON_TO_HASS = {
    1: FAN_LOW,
    2: FAN_MEDIUM,
    3: FAN_HIGH,
    0: FAN_AUTO
}

MAP_FAN_HASS_TO_EKON = {
    FAN_LOW: 1,
    FAN_MEDIUM: 2,
    FAN_HIGH: 3,
    FAN_AUTO: 0
}

@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    _LOGGER.info('Setting up Ekon climate platform')
    name = config.get(CONF_NAME)
    base_url = config.get(CONF_URL_BASE)
    timeout = config.get(CONF_TIMEOUT)
    username = config.get(CONF_USERNAME)
    password = config.get(CONF_PASSWORD)

    _LOGGER.info('Creating Ekon climate controller')
    EkonClimateController(hass, async_add_devices, name, base_url, username, password)


class EkonClimateController():
    """Ekon user account, inside this account there are all the ACs""" 
    def __init__(self, hass, async_add_devices, name, base_url, username, password):
        self._http_session = requests.Session()
        self.hass = hass
        self._async_add_devices = async_add_devices
        self._name = name
        self._base_url = base_url
        self._username = username
        self._password = password
        self._devices = {}

        # Now since I don't have a clue in how to develop inside HASS, I took some ideas and implementation from HASS-sonoff-ewelink
        if not self.do_login():
            return

        for dev_raw in self.query_devices():
            _LOGGER.info('Adding Ekon climate device to hass')
            newdev = EkonClimate(self, dev_raw['mac'], dev_raw['id'],
                dev_raw[EKON_PROP_ONOFF], dev_raw[EKON_PROP_MODE], dev_raw[EKON_PROP_FAN], dev_raw[EKON_PROP_TARGET_TEMP], dev_raw[EKON_PROP_ENVIROMENT_TEMP], dev_raw['envTempShow'], dev_raw['light']
            )
            self._devices[dev_raw['mac']] = newdev
            async_add_devices([newdev])


    def query_devices(self):
        """json response .... 'attachment': [< array of hvacs >]"""
        """ Each hvac is like """
        # [{'id': xxx, 'mac': 'xxxxxxxxxxxx', 'onoff': 85, 'light': 0, 'mode': 17, 'fan': 1, 'envTemp': 23, 'envTempShow': 23, 'tgtTemp': 24}]
        url = self._base_url + '/dev/allStatus'
        result = self._http_session.get(url)
        if(result.status_code!=200):
            _LOGGER.error ("Error query_devices")
            return False
        attch = json.loads(result.content)['attachment']
        _LOGGER.info ("query_devices")
        _LOGGER.info (attch)
        return attch  

    def do_login(self):
        url = self._base_url + 'j_spring_security_check'
        url_params = {
            'username': self._username,
            'password': self._password,
            'remember-me': 'true',
            'isServer': 'false',
            'device-id': '02:00:00:00:00:00',
            'isDebug': 'tRue'
        }
        result = self._http_session.post(url, params=url_params, data="")
        if(result.status_code!=200):
            _LOGGER.error('EKON Login failed! Please check credentials!')
            _LOGGER.error(result.content)
            return False
        _LOGGER.debug('EKON Login Sucsess')
        return True

    def refreshACs(self):
        self._devices
        for dev_raw in self.query_devices():
            """Refresh the only refreshed stuff 
            'mac': _mac_addr, # We won't sync it; 1-time read.
            'onoff': onoff, 
            'mode': mode, 
            'fan': fan, 
            'envTemp': env_temp, 
            'tgtTemp': target_temp
            """
            _LOGGER.info('(controller) Refreshing HVAC Data')
            dev = self._devices[dev_raw['mac']]
            ekon_state = self._devices[dev_raw['mac']]._ekon_state_obj
            ekon_state[EKON_PROP_FAN] = dev_raw[EKON_PROP_FAN]
            ekon_state[EKON_PROP_ONOFF] = dev_raw[EKON_PROP_ONOFF]
            ekon_state[EKON_PROP_MODE] = dev_raw[EKON_PROP_MODE]
            ekon_state[EKON_PROP_ENVIROMENT_TEMP] = dev_raw[EKON_PROP_ENVIROMENT_TEMP]
            ekon_state[EKON_PROP_TARGET_TEMP] = dev_raw[EKON_PROP_TARGET_TEMP]

class EkonClimate(ClimateEntity):
    #'onoff': 85, 'light': 0, 'mode': 17, 'fan': 1, 'envTemp': 23, 'envTempShow': 23, 'tgtTemp': 24
    def __init__(self, controller, _mac_addr, id, onoff, mode, fan, target_temp, env_temp, env_temp_show, light):
        _LOGGER.info('Initialize the Ekon climate device')
        self._controller = controller
        self._id = id
        self._name = "Ekon" + str(id)
        self._mac_addr = _mac_addr

        self._target_temperature_step = 1
        # Ekon works with celsius only
        self._unit_of_measurement = TEMP_CELSIUS
        
        # The part that is synced; missing/unused/no idea: uid, env_temp_show, light
        self._ekon_state_obj = {
            'mac': _mac_addr, # We won't sync it; 1-time read.
            'onoff': onoff, 
            'mode': mode, 
            'fan': fan, 
            'envTemp': env_temp, # RO
            'tgtTemp': target_temp, # RO
        }
        
        # Hack? see later
        self._last_on_state=False
        if onoff != EKON_VALUE_ON:
            self._last_on_state=False
        self.SyncEkonObjToSelf()

    def SyncEkonObjToSelf(self):
        self._current_temperature = self._ekon_state_obj[EKON_PROP_ENVIROMENT_TEMP]
        self._target_temperature = self._ekon_state_obj[EKON_PROP_TARGET_TEMP]
        
        # AFAIK
        self._min_temp = 16
        self._max_temp = 32

        # Figure out HASS HVAC Mode from EKON
        ekon_onoff = self._ekon_state_obj[EKON_PROP_ONOFF]
        if ekon_onoff == EKON_VALUE_ON:
            ekon_mode = self._ekon_state_obj[EKON_PROP_MODE]
            self._hvac_mode = MAP_MODE_EKON_TO_HASS[ekon_mode]
        else:
            self._hvac_mode = HVAC_MODE_OFF
        
        self._fan_mode = MAP_FAN_EKON_TO_HASS[self._ekon_state_obj[EKON_PROP_FAN]]


    def SyncSelfToEkonObj(self):
        _LOGGER.info("SyncSelfToEkonObj")
        self._ekon_state_obj[EKON_PROP_TARGET_TEMP] = self._target_temperature

        if self._hvac_mode == HVAC_MODE_OFF:
            self._ekon_state_obj[EKON_PROP_ONOFF] = EKON_VALUE_OFF
        else:
            self._ekon_state_obj[EKON_PROP_ONOFF] = EKON_VALUE_ON
            self._ekon_state_obj[EKON_PROP_MODE] = MAP_MODE_HASS_TO_EKON[self._hvac_mode]       
        self._ekon_state_obj[EKON_PROP_FAN] = MAP_FAN_HASS_TO_EKON[self._fan_mode]

    def TurnOnOff(self, state):
        url = self._controller._base_url + 'dev/switchHvac/' + self._ekon_state_obj["mac"] + '?on='

        _LOGGER.info("onoff changed is_on: %r" % state)
        if state:
            self._last_on_state = True
            url = url + 'True'
        else:
            self._last_on_state = False
            url = url + 'False'

        result = self._controller._http_session.get(url)
        if(result.status_code!=200):
            _LOGGER.error(result.content)
            _LOGGER.error("TurnOnOff (onoff)error")
            return False
        return True
        
    def SyncAndSet(self):
        self.SyncSelfToEkonObj()
        url = self._controller._base_url + 'dev/setHvac'
        # mac, onoff, mode, fan, envtemp, tgttemp, 
        _LOGGER.info('Syncing to remote, state')
        _LOGGER.info(str(json.dumps(self._ekon_state_obj)))
        result = self._controller._http_session.post(url, json=self._ekon_state_obj)
        if(result.status_code!=200):
            _LOGGER.error(result.content)
            _LOGGER.error("SyncAndSet (properties)error")
            return False
        # Damn server has delay/race condition syncing the value we just set, so that it will be the one read next time
        # In other words, if we setHvac and getDevice immidiatly, values might be the old one, so HA would look like it hadn't changed
        time.sleep(1)
        # TODO: Check response json returnCode {"returnCode":0,"values":null} ; 0 OK, -72 Device offiline; -73 see belo. other fail 
        """                 case -73:
                                StringBuilder sb = new StringBuilder();
                                sb.append("temp outrage for device ");
                                sb.append(cVar);
                                StringBuilder.m3719b(sb.toString());
                                JSONArray jSONArray = jSONObject.getJSONArray("values");
                                if (jSONArray.length() > 0) {
                                    Album a = Album.m3577a(jSONArray.getJSONObject(0));
                                    HomePageActivity.this.mo3201b().f2190a.put(a.mo3382h(), a);
                                    if (a.mo3382h().equals(HomePageActivity.this.f2352x.mo3328c())) {
                                        HomePageActivity.this.mo3084b(a);
                                        return;
                                    }
                                    return;
                                }
                                return;
                            case -72:
                                Context.m3722a(HomePageActivity.this.getString(R.string.device_offline), 0);
                                imageButton = HomePageActivity.this.f2349u;
                                break;
                            default:
                                Context.m3722a(HomePageActivity.this.getString(R.string.operation_failure), 0);
                                imageButton = HomePageActivity.this.f2349u;
                                break;
        """
        _LOGGER.info(result.content)
        return True
    
    def GetAndSync(self):
        self._controller.refreshACs()
        # Sync in
        self.SyncEkonObjToSelf()
    
    def SendStateToAc(self, timeout):
        _LOGGER.info('Start sending state to HVAC')
        obj = {
            'mac': self._ekon_state_obj['mac'], 
            'onoff': self._ekon_state_obj['onoff'], 
            'mode': self._ekon_state_obj['mode'], 
            'fan': self._ekon_state_obj['fan'], 
            'envTemp': self._ekon_state_obj['envTemp'], 
            'tgtTemp': self._ekon_state_obj['tgtTemp']
        }
        url = self._controller._base_url + 'dev/setHvac'
        result = self._controller._http_session.post(json=obj)
        if(result.status_code!=200):
            _LOGGER.error("SendStateToAc faild")
            _LOGGER.errpr(result.content)
            return False
        return True

    @property
    def should_poll(self):
        _LOGGER.info('should_poll()')
        # Return the polling state.
        return True

    def update(self):
        _LOGGER.info('update()')
        # Update HA State from Device
        self.GetAndSync()

    @property
    def name(self):
        _LOGGER.info('name(): ' + str(self._name))
        # Return the name of the climate device.
        return self._name

    @property
    def temperature_unit(self):
        _LOGGER.info('temperature_unit(): ' + str(self._unit_of_measurement))
        # Return the unit of measurement.
        return self._unit_of_measurement

    @property
    def current_temperature(self):
        _LOGGER.info('current_temperature(): ' + str(self._current_temperature))
        # Return the current temperature.
        return self._current_temperature

    @property
    def min_temp(self):
        _LOGGER.info('min_temp(): ' + str(MIN_TEMP))
        # Return the minimum temperature.
        return MIN_TEMP
        
    @property
    def max_temp(self):
        _LOGGER.info('max_temp(): ' + str(MAX_TEMP))
        # Return the maximum temperature.
        return MAX_TEMP
        
    @property
    def target_temperature(self):
        _LOGGER.info('target_temperature(): ' + str(self._target_temperature))
        # Return the temperature we try to reach.
        return self._target_temperature
        
    @property
    def target_temperature_step(self):
        _LOGGER.info('target_temperature_step(): ' + str(self._target_temperature_step))
        # Return the supported step of target temperature.
        return self._target_temperature_step

    @property
    def hvac_mode(self):
        _LOGGER.info('hvac_mode(): ' + str(self._hvac_mode))
        # Return current operation mode ie. heat, cool, idle.
        return self._hvac_mode

    @property
    def hvac_modes(self):
        _LOGGER.info('hvac_modes(): ' + str(HVAC_MODES))
        # Return the list of available operation modes.
        return HVAC_MODES

    @property
    def fan_mode(self):
        _LOGGER.info('fan_mode(): ' + str(self._fan_mode))
        # Return the fan mode.
        return self._fan_mode

    @property
    def fan_modes(self):
        _LOGGER.info('fan_list(): ' + str(FAN_MODES))
        # Return the list of available fan modes.
        return FAN_MODES
        
    @property
    def supported_features(self):
        _LOGGER.info('supported_features(): ' + str(SUPPORT_FLAGS))
        # Return the list of supported features.
        return SUPPORT_FLAGS        
 
    def set_temperature(self, **kwargs):
        _LOGGER.info('set_temperature(): ' + str(kwargs.get(ATTR_TEMPERATURE)))
        # Set new target temperatures.
        if kwargs.get(ATTR_TEMPERATURE) is not None:
            # do nothing if temperature is none
            self._target_temperature = int(kwargs.get(ATTR_TEMPERATURE))
            self.SyncAndSet()
            # I'm not sure what this does in POLLING mode (Should poll True), But I guess it would make HASS
            # Perform a poll update() and refresh new data from the server
            self.schedule_update_ha_state()

    def set_fan_mode(self, fan):
        _LOGGER.info('set_fan_mode(): ' + str(fan))
        # Set the fan mode.
        self._fan_mode = fan
        self.SyncAndSet()
        self.schedule_update_ha_state()

    def set_hvac_mode(self, hvac_mode):
        _LOGGER.info('set_hvac_mode(): ' + str(hvac_mode))
        if hvac_mode == HVAC_MODE_OFF:
            self.TurnOnOff(False)
            return
        
        # Set new operation mode.
        prev_mode = self._hvac_mode
        self._hvac_mode = hvac_mode
        self.SyncAndSet()
        # And only after turn on? if needed
        if prev_mode==HVAC_MODE_OFF:
            # if was off, turn on after configuring mode
            self.TurnOnOff(True)

        self.schedule_update_ha_state()

    @asyncio.coroutine
    def async_added_to_hass(self):
        _LOGGER.info('Ekon climate device added to hass()')
        self.GetAndSync()
