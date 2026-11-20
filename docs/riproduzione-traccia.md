# Riproduzione traccia: stato e criteri di abilitazione

**20 novembre 2026 — sviluppo locale, non installato né verificato sul Rover fisico.**

La pagina `riproduzione.html` è separata da `autopilota.html`, che resta la postazione di teleoperazione e registrazione. La pagina nuova elenca le missioni sul Rover, legge un geofence GeoJSON dal browser o da un file, chiede al server di validare la traccia e mostra l'anteprima live. Non contiene un comando di partenza. I motori non ricevono comandi dalla funzione di riproduzione.

`modules/route_replay.py` verifica che la missione abbia almeno due posizioni distinte, punti RTK FIX, timestamp crescenti quando presenti, nessun salto maggiore di 5 m fra campioni e un percorso interamente dentro un singolo poligono GeoJSON con margine iniziale di 0,75 m dal bordo. Il margine è riferito alla posizione del ricevitore/centro, non all'ingombro completo del rover. La geometria del poligono va ancora verificata sul campo; non basta il dato salvato nel browser per autorizzare il movimento.

Il loop del server aggiorna l'anteprima a 5 Hz. Rifiuta posizione senza FIX o più vecchia di 1,5 s, correzioni RTCM più vecchie di 3 s, posizione fuori geofence, errore laterale oltre 0,8 m, meta entro 0,5 m e target dietro al rover. Usa il course GNSS solo in movimento (almeno 1,8 km/h) e se aggiornato entro 1,5 s; sotto tale velocità richiede una IMU recente e un offset/verso calibrati. Non è ancora presente una calibrazione di yaw per il Rover, perciò la posa può essere indisponibile da fermo. Il parser GNSS ora registra il tempo dell'ultimo RMC per distinguere un course vecchio da uno recente.

`MotorCalibration` trasforma velocità ruota richieste e curvatura in percentuali nominali SX/DX tramite due curve misurate e una rampa. È codice passivo e rifiuta extrapolazioni oltre le misure: i parametri non sono ancora disponibili. Il CSV di `tools/analyze_motor_calibration.py` sarà il punto di partenza per rivedere e costruire queste curve dopo la prova rettilinea, includendo differenze fra le due ruote. Il trim esistente resta applicato al confine del driver.

## Cosa manca prima del movimento automatico

1. Misurare velocità/comando con la nuova registrazione e definire carreggiata effettiva, accelerazione/decelerazione, velocità massima e comportamento in curva. Non copiare i valori di Webots sul robot.
2. Calibrare il verso e l'offset della IMU e verificare la coerenza GNSS/IMU, specialmente a bassa velocità e all'avvio. Il GNSS a 1 Hz e il course over ground da soli non danno un heading affidabile da fermo.
3. Installare un monitor ostacoli sul Rover che produca una misura fresca e verificata. Al momento i prototipi LiDAR/camera non alimentano il controllo: il gate ostacoli resta intenzionalmente chiuso.
4. Portare il geofence verificato in una configurazione locale del Rover, validare poligono, margini, ingombro e distanza di arresto, e bloccare il movimento se manca. La copia inviata dal browser serve solo per l'anteprima.
5. Collegare la funzione di controllo agli attuatori con priorità assoluta a stop manuale, perdita di dati, geofence, ostacoli e watchdog. Registrare ogni comando e causa di arresto. Aggiungere un arresto indipendente dal processo Python per la sicurezza fisica.
6. Verificare con test progressivi: simulazione, ruote sollevate, area libera con apparato di taglio disconnesso, poi prove ripetute con metriche di errore laterale e distanza di arresto. Il semplice arrivo alla meta non misura affidabilità né sicurezza.

I limiti numerici dell'anteprima sono valori iniziali conservativi per individuare dati incoerenti: non sono ancora soglie validate per questo telaio o questo vigneto.
