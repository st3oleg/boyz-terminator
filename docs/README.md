# Documentazione Terminator

Questa documentazione descrive il repository presente e valuta il percorso verso un robot RTK per lo sfalcio. È stata redatta il 12 novembre 2026 esaminando i file versionati e il documento esterno `Storico Google.md`.

## Documenti

- [Analisi del codice e dello storico](analisi-codice.md): componenti realmente presenti, differenze rispetto allo storico e vulnerabilità prioritarie.
- [Studio di efficacia e fattibilità](fattibilita-efficacia.md): benefici possibili, limiti sul campo, valutazione economica e quadro normativo da verificare.
- [Specifiche obiettivo e piano di sviluppo](specifica-e-piano.md): architettura proposta, requisiti da definire e fasi per arrivare a prove sicure.

## Sintesi

Il repository è una base di telemetria e teleoperazione. Riceve NMEA e dati IMU, comanda due motori differenziali, trasmette video e registra una traccia GPS. La mappa consente di disegnare, modificare e cancellare perimetri virtuali, salvati nel browser della console; la pagina Scatter raccoglie i fix Rover via WebSocket. Queste funzioni di interfaccia non costituiscono ancora un geofence applicato dal controllore del robot: non ci sono guida autonoma, pianificazione della copertura, correzioni RTCM/NTRIP, dati GNSS Base nel flusso corrente, controllo di un apparato di taglio, sensori di ostacolo integrati o una catena di arresto di sicurezza indipendente.

Requisito d'impiego richiesto: l'autonomia dovrà essere consentita solo entro i perimetri autorizzati; fuori da essi il robot potrà essere comandato solo manualmente. Prima di abilitare l'autonomia, i perimetri dovranno essere disponibili e verificati dal controllore a bordo, insieme a margini coerenti con errore GNSS, dimensioni del veicolo e distanza di arresto.

**Conclusione:** il concetto è plausibile per sfalcio frequente e leggero, soprattutto in appezzamenti piccoli e regolari; il codice attuale non dimostra né efficacia agronomica né sicurezza per l'uso autonomo. Prima di qualsiasi prova con lame attive, occorrono progettazione e validazione della sicurezza macchina.

## Come leggere questo materiale

Le affermazioni sul comportamento del software sono riferite ai file effettivamente trovati nel repository. `Storico Google.md` è materiale storico: contiene anche esempi, desiderata e istruzioni operative, che non vengono trattati come funzionalità implementate né come ordini da eseguire. La valutazione di efficacia è una stima di fattibilità basata su studi pubblicati, non una promessa di prestazioni per questo prototipo. Il riepilogo normativo non è una valutazione di conformità.

