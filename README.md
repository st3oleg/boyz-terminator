# Comandi operativi del Rover

Guida rapida per avviare il Rover e lanciare i programmi di prova presenti in `tests/`. I comandi assumono che il progetto sia installato sul Raspberry in `/home/terminator/Documents`, come configurato in `telemetry_server.py`.

## Avvio del Rover

### Arrestare i processi precedenti

```bash
sudo killall -q -9 python3 ustreamer 2>/dev/null || true
```

Questo comando termina **tutti** i processi chiamati `python3` e `ustreamer`, inclusi i test LiDAR, camera e motori eventualmente attivi. Usalo solo quando vuoi fermare tutte queste attività; se devi chiuderne una sola, usa `Ctrl+C` nel terminale in cui l'hai avviata.

### Avviare il server Rover

```bash
python3 /home/terminator/Documents/telemetry_server.py
```

Lascia aperto il terminale mentre usi il Rover. Per arrestare il server, premi `Ctrl+C` in quel terminale.

- Mappa: `http://terminator.local:8080` oppure `http://<IP_DEL_RASPBERRY>:8080`
- Autopilota/teleoperazione: `http://terminator.local:8080/autopilota.html`

Sostituisci `<IP_DEL_RASPBERRY>` con l'indirizzo LAN o Tailscale effettivo. Il pulsante **Autopilota** nell'index apre `autopilota.html`.

## Aggiornamento della pagina nel browser

In Chrome su Windows, usa `Ctrl+Shift+F5`, `Ctrl+Shift+R` oppure `Ctrl+F5` per ricaricare la pagina ignorando la cache. Puoi farlo dopo aver aggiornato i file HTML sul Raspberry.

## Posizione antenna Base RTK

La mappa mostra il marker 📡 solo quando il server riceve coordinate Base valide. Impostare `BASE_LAT` e `BASE_LON` nell'ambiente del servizio Rover con le coordinate reali dell'antenna, poi riavviare il server e ricaricare la pagina. Senza queste coordinate il marker resta nascosto: il server non riceve al momento la posizione GNSS della Base e non deve inventarne una.

Esempio per un avvio manuale (sostituire i valori con quelli misurati):

```bash
BASE_LAT=45.905500 BASE_LON=12.438000 python3 /home/terminator/Documents/telemetry_server.py
```

Lo stato mostrato in mappa riflette la qualità NMEA ricevuta dal rover. `SINGLE` significa soluzione autonoma senza RTK; `FIX` richiede una soluzione RTK fixed dal ricevitore e correzioni funzionanti.

## Programmi di test

Gli script si trovano in `/home/terminator/Documents/tests/`. Esegui ogni prova in un terminale separato e termina con `Ctrl+C` o con il comando indicato.

### Mappa 2D del LiDAR

```bash
python3 /home/terminator/Documents/tests/test_lidar.py
```

Il programma legge il COIN-D6 da `/dev/ttyUSB0` a 230400 baud e avvia la pagina sulla porta `8085`:

- `http://terminator.local:8085`
- `http://<IP_DEL_RASPBERRY>:8085`

Premi `Ctrl+C` nel terminale per chiudere il server LiDAR. Se il sensore non viene rilevato, controlla il collegamento seriale e il nome della porta.

### Prova manuale dei motori

```bash
python3 /home/terminator/Documents/tests/test_motori.py
```

È un test diretto del driver Cytron: i tasti `W/S` comandano avanti/indietro, `A/D` la rotazione, `1/2` un motore alla volta, `T` avvia una sequenza automatica fino al 60%, `Spazio` porta i comandi a zero e `Q` esce. All'uscita lo script prova a riportare i motori al neutro.

**Prima della prova**, solleva le ruote o immobilizza il veicolo, tieni libera l'area e scollega l'apparato di taglio. Nel file i commenti e le etichette indicano il motore sinistro su GPIO 19 e il destro su GPIO 23, ma le costanti effettivamente usate dal programma sono invertite (`PIN_SX = 23`, `PIN_DX = 19`). Verifica cablaggio e assegnazione dei pin sul Raspberry prima di alimentare i motori.

### Prova delle videocamere

```bash
python3 /home/terminator/Documents/tests/test_camera.py
```

La regia di prova è sulla porta `8081` e avvia le camere USB e CSI quando le rileva:

- `http://terminator.local:8081`
- `http://<IP_DEL_RASPBERRY>:8081`

La prova camera usa la stessa porta `8081` del primo stream avviato da `telemetry_server.py`; non eseguire i due programmi contemporaneamente. Termina la prova con `Ctrl+C`.

## Riferimento ai file

| Script | Funzione | Porta/interfaccia |
|---|---|---|
| `telemetry_server.py` | Telemetria, mappa, teleoperazione e stream video del Rover | HTTP `8080`, video `8081` e `8082`, WebSocket `/ws` |
| `tests/test_lidar.py` | Acquisizione LiDAR e visualizzazione mappa 2D | Seriale `/dev/ttyUSB0` a `230400`; pagina `8085` |
| `tests/test_motori.py` | Comando diretto dei motori Cytron | GPIO; tastiera del terminale |
| `tests/test_camera.py` | Prova/regia delle videocamere | Pagina `8081`; stream USB interni `8082` e `8083` |

I test hardware non sono avviati automaticamente dal server Rover. Avviali solo quando serve provare il componente corrispondente.

## Integrazione RTK Base / Rover

Il codice locale per client RTCM Rover, uplink API, archivio Base e frontend statico configurabile è stato aggiunto; non è ancora stato installato o verificato sui Raspberry. Lo stato verificato, i gap residui e la procedura sono in [docs/architettura-rtk-base-rover.md](docs/architettura-rtk-base-rover.md).

La pagina statica in `static/` è pubblicabile su Netlify tramite `netlify.toml`. Impostare `apiBaseUrl` in `static/runtime-config.js` a un endpoint HTTPS della Base raggiungibile dal browser Tailscale. Netlify da solo non rende pubbliche le API private Tailscale; per accesso senza VPN servirà un endpoint relay autenticato.

Il Rover usa le variabili `BASE_TAILSCALE_HOST`, `BASE_RTCM_PORT` (predefinita `5000`), `BASE_API_URL` e `BASE_API_TOKEN` per collegamento RTCM e uplink. Non inserire il token nel frontend o nel repository.
