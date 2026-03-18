# Wi-Spy Field Station

## Doel

Dit project dient om een Raspberry Pi met Wi-Spy DBx te gebruiken als draagbaar spectrum meetstation voor field troubleshooting.

De Raspberry Pi functioneert als sensor en host een live visualisatie die op een laptop via browser bekeken kan worden, zonder extra software-installatie op de laptop.

## Use case

Voorbeeldscenario:

- Raspberry Pi + Wi-Spy DBx worden meegenomen naar een klant
- de Pi verzamelt live spectrumdata
- de gebruiker bekijkt de waterfall live op een company-owned laptop
- de laptop heeft bij voorkeur geen lokale installatie nodig
- wifi-analyse gebeurt apart via WinFi
- dit project focust op RF spectrum / interferentie visualisatie

## Doelstellingen

- live waterfall visualisatie via browser
- Raspberry Pi als standalone sensor
- geen lokale installatie nodig op kijktoestel
- bruikbaar in field troubleshooting
- later uitbreidbaar met logging, hotspot mode en exports

## Hardware

- Raspberry Pi
- Wi-Spy DBx
- voeding voor Raspberry Pi
- optioneel: portable monitor of hotspot setup
- laptop voor live viewing

## Software

- Raspberry Pi OS
- Python 3
- Git
- eventuele Python libraries voor visualisatie en webserver
- Kismet mag geïnstalleerd blijven, maar is niet de hoofdtool voor waterfall visualisatie

## Projectstructuur

wispy-field-station/
├── README.md
├── roadmap.md
├── scripts/
├── docs/
└── config/
