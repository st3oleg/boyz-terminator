# Documentazione Terminator

Questa documentazione descrive il repository e il percorso verso un robot RTK per lo sfalcio. La valutazione iniziale è del 12 novembre 2026. Le guide di calibrazione e riproduzione sono aggiornate al 24 novembre 2026 e includono i dati delle prove manuali del 23 novembre.

## Documenti

- [Analisi del codice e dello storico](analisi-codice.md): componenti realmente presenti, differenze rispetto allo storico e vulnerabilità prioritarie.
- [Studio di efficacia e fattibilità](fattibilita-efficacia.md): benefici possibili, limiti sul campo, valutazione economica e quadro normativo da verificare.
- [Specifiche obiettivo e piano di sviluppo](specifica-e-piano.md): architettura proposta, requisiti da definire e fasi per arrivare a prove sicure.
- [Analisi e verifica GPS RTK](gap_analisi_risoluzione_GPSRTK.md): configurazione osservata, procedura ripetibile di verifica RTCM/seriale/GNSS e gap prima della guida autonoma.
- [Architettura RTK Base / Rover](architettura-rtk-base-rover.md): stato dell'integrazione RTCM/Tailscale e piano per API Base e frontend indipendente.
- [Hub Ubuntu per i dispositivi](hub-ubuntu.md): Hub operativo, archivio, dashboard e avvio su richiesta del Rover.
- [Fase 1 dell'hub Ubuntu](fase-1-hub-ubuntu.md): flussi verificati, volume dei JSON, misure di rete da eseguire e contratto dati proposto.
- [Fase 2 dell'hub Ubuntu](fase-2-hub-ubuntu.md): avvio di API, PostgreSQL e dashboard, prova con dispositivi simulati e verifica del ripristino.
- [Calibrazione motori e dati delle tracce](calibrazione-motori-e-tracce.md): trim differenziale, misure con le ruote riparate e profilo PWM per Pure Pursuit.
- [Riproduzione traccia](riproduzione-traccia.md): registrazione, anteprima web, andata e raccordo da terminale, risultati di simulazione e stato della prova reale.
- [Video, telemetria e rete](video-telemetria-e-rete.md): camere USB/CSI, cinque preset, significato di PING e RTT, diagnosi di latenza e versioni Git discusse.
- [Visione, LiDAR e fusione sensori](gap-visione-lidar-fusione.md): configurazione riferita e funzioni ancora da progettare o verificare.
- [Piano di unificazione del rilievo](piano-unificazione-rilievo.md): proposta storica per GCS, Rover e Base, distinta dal software già implementato.

## Sintesi

Il repository fornisce telemetria e teleoperazione. Riceve NMEA e dati IMU, comanda due motori differenziali, trasmette video e registra tracce GPS con qualità RTK e diagnostica. Le correzioni RTCM arrivano su TCP privato dalla Base. Il controllore sperimentale da terminale collega Pure Pursuit a `MotorDriver` per una tratta in avanti supervisionata e legge un geofence locale. La pagina web offre l'anteprima. Il completamento di una corsa autonoma sul Rover fisico non è ancora confermato. Restano da realizzare o validare la pianificazione della copertura, il comando di un apparato di taglio e l'integrazione di sensori ostacolo.

Requisito d'impiego richiesto: l'autonomia dovrà essere consentita solo entro i perimetri autorizzati; fuori da essi il robot potrà essere comandato solo manualmente. Prima di abilitare l'autonomia, i perimetri dovranno essere disponibili e verificati dal controllore a bordo, insieme a margini coerenti con errore GNSS, dimensioni del veicolo e distanza di arresto.

**Conclusione:** il concetto è plausibile per sfalcio frequente e leggero, soprattutto in appezzamenti piccoli e regolari; il codice attuale non dimostra né efficacia agronomica né sicurezza per l'uso autonomo. Prima di qualsiasi prova con lame attive, occorrono progettazione e validazione della sicurezza macchina.

## Come leggere questo materiale

Le affermazioni sul comportamento del software sono riferite ai file effettivamente trovati nel repository. Le note citano anche `Storico Google.md` come materiale storico, ma quel file non è presente in questo checkout; le sue indicazioni non sono considerate funzionalità implementate. La valutazione di efficacia è una stima di fattibilità basata su studi pubblicati, non una promessa di prestazioni per questo prototipo. Il riepilogo normativo non è una valutazione di conformità.


## Integrazione RTK Base / Rover

Per il requisito attuale Base LC29H-BS / Rover LC29H-DA, fare riferimento a [Architettura RTK Base / Rover](architettura-rtk-base-rover.md): codice locale RTCM/Tailscale, persistenza dell'ultima posizione, precedente piano per il frontend Netlify e passaggi di installazione. Il 27 novembre 2026 sono stati verificati la ricezione RTCM, il FIX da fermo, la posizione Base sulla mappa e l'avvio dall'Hub. La diagnostica e i limiti delle prove sono nella [verifica sul Rover](gap_analisi_risoluzione_GPSRTK.md#verifica-del-27-novembre-2026).

L'[Hub Ubuntu](hub-ubuntu.md) conserva i dati e serve la dashboard sul PC dell'operatore. La teleoperazione browser→Rover e il flusso RTCM Base→Rover restano diretti. Le misure di latenza della [fase 1](fase-1-hub-ubuntu.md) restano da acquisire. La [fase 2](fase-2-hub-ubuntu.md) descrive l'avvio con dati simulati. Per installare il servizio sull'HP, collegare la Base e registrare il Rover, usa il [repository HP-linux](https://github.com/st3oleg/HP-linux). Il checkout Rover include `modules/hub_reporter.py`, `modules/hub_outbox.py` e il test `tests/test_hub_outbox.py`. La presenza di questi file documenta l'integrazione nel codice locale. L'invio dal Raspberry richiede configurazione e una verifica sul dispositivo.

Il nucleo geometrico in `modules/pure_pursuit.py` è condiviso da Webots, anteprima e controllore da terminale. La simulazione della traccia `Fix_1` è descritta nel [README Webots](../../webots/README.md). Per trim e curva di calibrazione consultare [Calibrazione motori e dati delle tracce](calibrazione-motori-e-tracce.md). Per i risultati della verifica RTK consultare [Analisi e verifica GPS RTK](gap_analisi_risoluzione_GPSRTK.md).
