# Documentazione Terminator

Questa documentazione descrive il repository e il percorso verso un robot RTK per lo sfalcio. La valutazione iniziale è del 12 novembre 2026; stato RTK, registrazione e calibrazione motori sono aggiornati al 19 novembre 2026.

## Documenti

- [Analisi del codice e dello storico](analisi-codice.md): componenti realmente presenti, differenze rispetto allo storico e vulnerabilità prioritarie.
- [Studio di efficacia e fattibilità](fattibilita-efficacia.md): benefici possibili, limiti sul campo, valutazione economica e quadro normativo da verificare.
- [Specifiche obiettivo e piano di sviluppo](specifica-e-piano.md): architettura proposta, requisiti da definire e fasi per arrivare a prove sicure.
- [Analisi e verifica GPS RTK](gap_analisi_risoluzione_GPSRTK.md): configurazione osservata, procedura ripetibile di verifica RTCM/seriale/GNSS e gap prima della guida autonoma.
- [Calibrazione motori e dati delle tracce](calibrazione-motori-e-tracce.md): trim differenziale, campi registrati, curva velocità/comando e passaggi per la raccolta sul campo.
- [Riproduzione traccia](riproduzione-traccia.md): validazione, anteprima sul Rover e condizioni ancora necessarie prima del movimento automatico.

## Sintesi

Il repository fornisce telemetria e teleoperazione: riceve NMEA e dati IMU, comanda due motori differenziali, trasmette video e registra tracce GPS con qualità RTK e diagnostica. È presente un trasporto RTCM su TCP privato fra Base e Rover; non è un client NTRIP. Il nucleo geometrico Pure Pursuit esiste, ma non è ancora collegato agli attuatori. I poligoni della mappa sono salvati nel browser e non costituiscono un geofence applicato dal controllore. Restano da realizzare o validare il controllo autonomo integrato, la pianificazione della copertura, il comando di un apparato di taglio, l'integrazione di sensori ostacolo e una catena di arresto indipendente.

Requisito d'impiego richiesto: l'autonomia dovrà essere consentita solo entro i perimetri autorizzati; fuori da essi il robot potrà essere comandato solo manualmente. Prima di abilitare l'autonomia, i perimetri dovranno essere disponibili e verificati dal controllore a bordo, insieme a margini coerenti con errore GNSS, dimensioni del veicolo e distanza di arresto.

**Conclusione:** il concetto è plausibile per sfalcio frequente e leggero, soprattutto in appezzamenti piccoli e regolari; il codice attuale non dimostra né efficacia agronomica né sicurezza per l'uso autonomo. Prima di qualsiasi prova con lame attive, occorrono progettazione e validazione della sicurezza macchina.

## Come leggere questo materiale

Le affermazioni sul comportamento del software sono riferite ai file effettivamente trovati nel repository. `Storico Google.md` è materiale storico: contiene anche esempi, desiderata e istruzioni operative, che non vengono trattati come funzionalità implementate né come ordini da eseguire. La valutazione di efficacia è una stima di fattibilità basata su studi pubblicati, non una promessa di prestazioni per questo prototipo. Il riepilogo normativo non è una valutazione di conformità.


## Integrazione RTK Base / Rover

Per il requisito attuale Base LC29H-BS / Rover LC29H-DA, fare riferimento a [Architettura RTK Base / Rover](architettura-rtk-base-rover.md): codice locale RTCM/Tailscale, persistenza dell'ultima posizione, frontend Netlify e passaggi di installazione. La ricezione RTCM e il passaggio a FIX sono stati osservati con prove manuali; la versione completa d'integrazione deve ancora essere installata e verificata sui Raspberry.

Il nucleo geometrico Pure Pursuit è in `modules/pure_pursuit.py`; calcola target e curvatura su coordinate metriche, senza collegarsi agli attuatori. La simulazione della traccia `Fix_1` è descritta nel [README Webots](../../webots/README.md). Per trim e curva di calibrazione consultare [Calibrazione motori e dati delle tracce](calibrazione-motori-e-tracce.md); per i risultati della verifica RTK consultare [Analisi e verifica GPS RTK](gap_analisi_risoluzione_GPSRTK.md).
