# Wi-Spy Field Station Monorepo

Dit project bevat zowel de Raspberry Pi analyzer-engine als de centrale server/webapp.

## Structuur

- `pi/`  
  Raspberry Pi code voor capture, lokale analyzer UI, wifi-beheer en live data verzending naar de server.

- `server/`  
  Centrale server/webapp met dashboard, analyzer-overzicht, live detailpagina's, spectrum en waterfall.

## Huidige status

Deze repository is omgevormd naar een monorepo zodat Pi en server samen beheerd kunnen worden in één versiegeschiedenis.

## Belangrijke branches

- `main`  
  Stabiele hoofdlijn

- `monorepo-restructure`  
  Veilige branch waarop de monorepo-structuur is opgebouwd

## Belangrijke tags

- `v0.6.0-pi-pre-monorepo-backup`  
  Backup van de Pi-staat vóór de monorepo-omvorming

- `v0.7.0-monorepo-baseline`  
  Eerste veilige monorepo-baseline met `pi/` en `server/`

## Opmerking

Runtime-data zoals logs, uploads, lokale `.env` files en tijdelijke testbestanden worden niet mee opgenomen in Git.