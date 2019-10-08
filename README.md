# NOTE THIS IS NOT FULLY TESTED, NO RESPONSIBILITY WHATSOEVER
Using this component may effect your hass installation stability, may report falsly the state of your HVAC, commands may seem to be working but they might not (such situation where u think you turned off the ac, but it didn't)

# What types of HVACs? / ACs?
Short: Tadiran mini-central ACs, other iAircon/EKON/Airconet Based ACs
Long:
There's a compony out there Called EKON, They have a product named iAircon which is a esp8266 hardware device, or the marketing name 
"Airconet" (available on play store) that connects to the HVAC system

Unfortunately, No API or documentation exist for this cloud service. This is where this repo comes in

Israeli HVACs manefacturer "TADIRAN" Uses this ekon solution for their "Tadiran connect" product, designated for some of their "mini central hvacs"

# HomeAssistant-HomeAssistant-EKON-iAircon
EKON iAircon / Tadiran climate component written in Python3 for Home Assistant.
Built on the bases of Gree Climate component for easier interfacing with HASS


**Sources used:**
 - https://github.com/tomikaa87/gree-remote
 - https://github.com/vpnmaster/homeassistant-custom-components
 - https://developers.home-assistant.io/
 
## HACS
This component is NOT CURRENTLY added to HACS default repository list.

## Custom Component Installation

1. Copy the custom_components folder to your own hassio /config folder.

2. Choose the server you want to work with (AFAIK only Tadiran and EKON Main exist).
   If you are using Airconet app you are currently using the EKON Main server
   If you are using Tadiran connect app you are currently using (what I call) EKON Tadiran server

3. If you want to work on a server OTHER then the one you are currently using, setup an account with the app, reset the wifi-controller-thing and pair it with the app and the new account.
   For example, you might currently be using Tadiran connect app, but this component was only tested on the main server. Install "Airconet", login/create an account, on the tadiran connect electronics thing, press and hold the reset button. The button is reachabe via a hole in the plastic under the sticker. You can also open the plastic box carefully. Hold the buttun untill the led blinks in 2 colors (blue/purpule) the box is in pairing mode, now using the Airconet app, add it to your account.

4. In your configuration.yaml add the following:

   ```yaml
   climate: 
   - platform: ekon
     # This currently unused:
     name: Main account
     # Specify the name and password for your account
     username: my@account.com
     password: myPassword
     # This specifies the server that the component would work with, I have only tried it with EKON server (Airconet APP)
     # Optional, defults to Airconet server
     # EKON main server
     base_url: https://www.airconet.info/
     # EKON tadiran server
     # base_url: https://www.airconet.xyz/
   ```
5. OPTIONAL: Add info logging to this component (to see if/how it works)
  
   ```yaml
   logger:
     default: error
     logs:
       custom_components.ekon: debug
   ```