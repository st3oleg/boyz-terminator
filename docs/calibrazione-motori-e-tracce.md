# Calibrazione motori e dati delle tracce

**Aggiornato:** 19 novembre 2026  
**Stato:** modifiche software presenti nel checkout locale; non ancora installate/verificate sul Rover. La curva reale richiede nuove acquisizioni sul campo.

## Trim differenziale

La pagina `static/autopilota.html` include il cursore **Trim differenziale** da `-20%` a `+20%`, a passi dell'1%. Il valore viene inviato al server, applicato prima di `MotorDriver.set_motors()` e salvato in `/home/terminator/Documents/motor_calibration.json` (percorso predefinito; si può cambiare con `MOTOR_TRIM_CONFIG_PATH`). Se il file non esiste, si parte da `MOTOR_TRIM_PCT` o da `0%`.

La correzione è relativa al comando nominale:

```text
SX effettivo = SX nominale × (1 − trim / 100)
DX effettivo = DX nominale × (1 + trim / 100)
```

Il risultato è arrotondato a percentuale intera e limitato a `-100…+100%`. Un trim positivo aumenta DX e riduce SX; è il verso che tende a correggere una deriva verso destra in marcia avanti. Un trim negativo fa l'opposto. Per esempio, `40%` nominale con trim `+5%` dà circa `38%` a SX e `42%` a DX. La media resta circa invariata.

La UI continua a mostrare il comando nominale, normalmente a passi di 10%, e il trim in un indicatore separato. Le percentuali effettive e i PWM inviati al driver vengono registrati per l'analisi. Il trim non è una misura della potenza elettrica o della velocità della ruota: il sistema attuale non ha encoder né feedback di corrente.

## Dati salvati con la traccia

Il server salva in `missions/` JSON versione 3. Registra al massimo un campione per ogni nuovo aggiornamento GGA GNSS, tipicamente circa 1 Hz. Accetta coordinate non nulle con stato `FIX`, `FLOAT`, `DGPS` o `SINGLE`, purché l'aggiornamento sia recente (massimo 3 secondi); quindi una traccia non è automaticamente composta solo da FIX. Controllare `rtk_status` in ogni punto e filtrare a FIX per analisi RTK.

Ogni punto comprende:

- latitudine, longitudine, quota, timestamp fix ed età del fix;
- qualità RTK, satelliti, velocità e course over ground;
- yaw, pitch, roll ed età dell'ultimo dato IMU;
- ultimo comando motore ed età del comando;
- trim, comandi nominali SX/DX, uscite percentuali applicate al driver e PWM SX/DX;
- stato dry-run e connessione, byte ricevuti ed età delle correzioni RTCM.

Il blocco `diagnostic_events` registra gli eventi di comando, trim, stop, dry-run e watchdog con i valori nominali e quelli inviati al driver. Questi dati sono solo diagnostici: non entrano nel calcolo del Pure Pursuit e non cambiano i comandi.

## Ricavare una curva velocità/comando

`tools/analyze_motor_calibration.py` crea un CSV diagnostico con velocità mediana, minima e massima per livello motore. Calcola la velocità dallo spostamento fra posizioni GNSS consecutive e dai timestamp del fix; non usa la velocità istantanea del ricevitore.

Sono usati solo intervalli con:

- `FIX` su entrambi i campioni;
- dry-run disattivato e trim `0%`;
- uscite motore uguali e non nulle sui due lati;
- almeno 2 secondi dall'ultimo comando a ciascun campione;
- intervallo temporale positivo e non superiore a 2,5 secondi.

Procedura per acquisire i dati:

1. Caricare i file software aggiornati sul Rover e riavviare il server.
2. In area aperta e sicura, con apparato di taglio disabilitato, attendere un FIX stabile.
3. Impostare trim `0%` e dry-run spento; registrare una missione nuova.
4. Percorrere tratti rettilinei separati ai diversi gradini nominali (20%, poi incrementi di 10%). Mantenere ogni gradino per alcuni secondi prima di passare al successivo. Registrare anche il verso inverso se serve la curva di retromarcia.
5. Fermare e salvare la missione. Copiare il JSON sul PC o eseguire lo script direttamente sul Rover:

```bash
python3 /home/terminator/Documents/tools/analyze_motor_calibration.py /home/terminator/Documents/missions/<nome_traccia>.json
```

Lo script scrive `<nome_traccia>.calibration.csv` accanto al JSON. La curva può essere popolata solo da una registrazione nuova con questi campi; `Fix_1.json` è precedente al salvataggio dei comandi motore e non contiene i dati necessari.

## Uso futuro con Pure Pursuit

`modules/pure_pursuit.py` calcola target e curvatura geometrica; non invia ancora comandi agli attuatori. Una volta misurata e revisionata, la curva potrà convertire la velocità richiesta dal controllore nel comando nominale motore (lookup o interpolazione). Il trim verrà applicato successivamente, al confine del driver, per correggere una differenza fra i lati. La curva attuale è solo diagnostica e non viene applicata automaticamente.

Prima di abilitare il controllo automatico restano da integrare il loop di controllo, la gestione di velocità e sterzata per il differenziale, limiti e rampe, validità/freschezza RTK, arresto su perdita GNSS/RTCM e verifiche di sicurezza indipendenti.

## Simulazione Webots su Fix_1

Nel progetto Webots è presente `worlds/Fix_1_test.wbt`, con GPS WGS84 e IMU attivi sul modello del rover. Il controller `fix1_pure_pursuit` carica la traccia `controllers/rover_bridge/missions/Fix_1.json` e riusa `modules/pure_pursuit.py` dal repository Rover. Il ricevitore simulato aggiorna il GPS a 1 Hz. Il controller registra log JSONL con errore laterale, flag di correzioni e comandi/setpoint motore Webots in `controllers/rover_bridge/runs/`.

In questa simulazione i punti `FIX` rappresentano soltanto che le correzioni sono considerate disponibili: Webots non riproduce il flusso RTCM binario e non apre una connessione NTRIP. I setpoint dei motori simulati e i parametri di crociera non sono potenze né velocità calibrate del rover reale. Per aprire il mondo e usare i controlli, seguire il [README Webots](../../webots/README.md).

## File coinvolti

- `telemetry_server.py`: trim, persistenza, metriche nei punti, eventi diagnostici e payload di telemetria.
- `static/autopilota.html`: cursore trim e visualizzazione separata dai comandi nominali.
- `modules/pure_pursuit.py`: geometria Pure Pursuit senza collegamento agli attuatori.
- `tools/analyze_motor_calibration.py`: estrazione CSV passiva.
- `missions/Fix_1.json`: traccia FIX storica senza campi potenza motore.
