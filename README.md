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
- Riproduzione traccia (validazione e anteprima, senza comando motori): `http://terminator.local:8080/riproduzione.html`

Sostituisci `<IP_DEL_RASPBERRY>` con l'indirizzo LAN o Tailscale effettivo. Il pulsante **Autopilota** nell'index apre `autopilota.html`.

## Aggiornamento della pagina nel browser

In Chrome su Windows, usa `Ctrl+Shift+F5`, `Ctrl+Shift+R` oppure `Ctrl+F5` per ricaricare la pagina ignorando la cache. Puoi farlo dopo aver aggiornato i file HTML sul Raspberry.

## Posizione antenna Base RTK

Il Rover legge la posizione di riferimento della Base da `GET /api/state` ogni 5 secondi e la invia alla mappa. Usa la stessa origine HTTP dell'uplink verso la Base. La Base determina le coordinate da RTCM 1005/1006 o da NMEA GGA quando disponibile.

```bash
BASE_TAILSCALE_HOST=100.85.248.82 python3 -u /home/terminator/Documents/telemetry_server.py
```

Se la Base non risponde o non ha coordinate valide, la mappa nasconde il marker. Le installazioni con `BASE_LAT` e `BASE_LON` già impostate usano quei valori come riserva. La posizione di riferimento non alimenta i campioni GNSS in Scatter Analysis.

Lo stato mostrato in mappa riflette la qualità NMEA ricevuta dal rover. `SINGLE` significa soluzione autonoma senza RTK; `FIX` richiede una soluzione RTK fixed dal ricevitore e correzioni funzionanti.

## Trim e curva di calibrazione motori

Il cursore **Trim differenziale** corregge una deriva costante: un valore positivo aumenta il comando del motore destro e riduce quello sinistro; un valore negativo fa l'opposto. È una correzione relativa: per esempio, a `40%` nominale e trim `+5%`, il driver riceve circa `38%` a sinistra e `42%` a destra. La media resta circa uguale. Il trim è applicato prima del driver, salvato in `motor_calibration.json` e limitato a ±20%. Sul front end restano visibili i comandi nominali (a passi del 10%); la traccia registra anche trim, percentuali inviate al driver e PWM effettivi.

Durante una prova di calibrazione rettilinea, lascia trim a `0%`, disattiva dry-run, percorri tratti dritti a ogni potenza nominale e attendi almeno 2 secondi dopo ogni cambio prima di raccogliere la velocità. Registra la prova con GNSS FIX. Il logger salva un punto a ogni nuovo aggiornamento GNSS (circa 1 Hz), insieme a velocità, comando motori, stato RTK, satelliti, orientamento IMU, età dei dati e stato/età RTCM. Queste metriche sono solo diagnostiche e non modificano i comandi né il Pure Pursuit.

Per estrarre il riepilogo CSV della curva misurata:

```bash
python3 /home/terminator/Documents/tools/analyze_motor_calibration.py /home/terminator/Documents/missions/<traccia_calibrazione>.json
```

Il programma calcola la velocità dallo spostamento tra posizioni GNSS consecutive e usa solo intervalli FIX con dry-run spento, trim zero, comandi uguali sui due lati e comando stabile da almeno 2 secondi. Produce velocità mediana/minima/massima per livello di potenza. Il CSV è diagnostico e non viene caricato automaticamente dal controllo. `Fix_1.json` precede il salvataggio delle potenze; le nuove prove a 30% e 50% sono state usate per costruire manualmente il profilo sperimentale `profilo_guida.json`. La guida completa è in [docs/calibrazione-motori-e-tracce.md](docs/calibrazione-motori-e-tracce.md).

## Riproduzione supervisionata da terminale

Il modulo `modules.follow_route` sul Raspberry usa Pure Pursuit e `profilo_guida.json`. La prova attuale seleziona il tratto in avanti di `MappaComandoGiusta_1795443596.json` fino al punto 46. Può raggiungere la partenza con un raccordo se il Rover è ancora nella posa finale di una registrazione di riferimento valida. La pagina **Riproduzione** rimane la postazione di anteprima. I comandi, i requisiti e lo stato del collaudo sono nella [guida di riproduzione](docs/riproduzione-traccia.md#controllore-locale-sul-raspberry).

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

Con `telemetry_server.py`, la camera CSI compare nella regia di `autopilota.html` accanto alle webcam USB. Il server usa `rpicam-vid` (o `libcamera-vid`) per pubblicare il video su `http://<IP_DEL_RASPBERRY>:8080/camera/csi/stream` e la miniatura su `/camera/csi/snapshot`. Se la camera non è disponibile, la pagina ritenta la connessione. Dopo aver aggiornato il codice sul Raspberry, riavvia `telemetry_server.py`.

Per vedere una sola camera con il ping del robot apri `http://<IP_DEL_RASPBERRY>:8080/camera/usb1`, `/camera/usb2` o `/camera/csi`. Il valore mostrato è il tempo di andata e ritorno di una piccola richiesta HTTP tra browser e server, non il ritardo dei fotogrammi. Gli indirizzi `/stream` sulle porte `8081` e `8082` restano flussi MJPEG per applicazioni video e non possono mostrare un indicatore HTML.

Il controllo **Immagine** delle due EMEET offre cinque livelli: Notturno+, Notturno, Bilanciato, Diurno e Sole forte. I due livelli estremi richiedono più esposizione/gain o meno esposizione rispetto ai tre preset precedenti. Il server legge i limiti V4L2 di ciascuna webcam e adatta i valori richiesti; il messaggio sotto al cursore mostra quelli realmente applicati. Un'immagine CSI fortemente rosa alla luce diurna può indicare una camera NoIR senza filtro infrarosso: in quel caso serve un filtro IR-cut per colori fedeli.

In Autopilota l'indicatore **PING** mostra sempre l'età della telemetria WebSocket (`ora del browser - timestamp inviato dal robot`); non è l'RTT HTTP delle pagine camera. Le miniature si aggiornano ogni 5 secondi; lo stream CSI è limitato a 960×540 e 10 fps per ridurre il traffico. I vecchi pulsanti FPS non modificavano lo stream e sono stati rimossi.

Per le verifiche di latenza, l'avvio lento della CSI, i limiti dei preset e i comandi Git discussi, consulta [docs/video-telemetria-e-rete.md](docs/video-telemetria-e-rete.md).

## Riferimento ai file

| Script | Funzione | Porta/interfaccia |
|---|---|---|
| `telemetry_server.py` | Telemetria, mappa, teleoperazione e stream video del Rover | HTTP `8080` (anche CSI), USB `8081` e `8082`, WebSocket `/ws` |
| `tests/test_lidar.py` | Acquisizione LiDAR e visualizzazione mappa 2D | Seriale `/dev/ttyUSB0` a `230400`; pagina `8085` |
| `tests/test_motori.py` | Comando diretto dei motori Cytron | GPIO; tastiera del terminale |
| `tests/test_camera.py` | Prova/regia delle videocamere | Pagina `8081`; stream USB interni `8082` e `8083` |

I test hardware non sono avviati automaticamente dal server Rover. Avviali solo quando serve provare il componente corrispondente.

## Integrazione RTK Base / Rover

Il codice locale per client RTCM Rover, uplink API, archivio Base e frontend statico configurabile è stato aggiunto; non è ancora stato installato o verificato sui Raspberry. Lo stato verificato, i gap residui e la procedura sono in [docs/architettura-rtk-base-rover.md](docs/architettura-rtk-base-rover.md).

L'[hub su PC Ubuntu](docs/hub-ubuntu.md) conserva i dati dei dispositivi in PostgreSQL e serve una dashboard web senza Supabase. La prima versione è in `hub/` e si avvia con la [procedura di fase 2](docs/fase-2-hub-ubuntu.md), che include un Rover e una Base simulati. La [fase 1](docs/fase-1-hub-ubuntu.md) raccoglie misure e definisce il formato dei dati. I comandi di teleoperazione e RTCM usano i collegamenti diretti.

La pagina statica in `static/` è pubblicabile su Netlify tramite `netlify.toml`. Impostare `apiBaseUrl` in `static/runtime-config.js` a un endpoint HTTPS della Base raggiungibile dal browser Tailscale. Netlify da solo non rende pubbliche le API private Tailscale; per accesso senza VPN servirà un endpoint relay autenticato.

Il Rover usa le variabili `BASE_TAILSCALE_HOST`, `BASE_RTCM_PORT` (predefinita `5000`), `BASE_API_URL` e `BASE_API_TOKEN` per collegamento RTCM e uplink. Non inserire il token nel frontend o nel repository.
