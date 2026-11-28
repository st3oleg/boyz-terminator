# Istruzioni per gli agenti

Queste istruzioni si applicano a tutto il repository. Le richieste esplicite dell'utente prevalgono sulle preferenze qui indicate. Usa le regole ingegneristiche come criteri pratici, non come obblighi formali.

Se il prompt indica un file, parti da quello e usa `rg` e `git diff -- <file>` per circoscrivere il lavoro. Nel workspace completo, la sezione **Dove iniziare per una modifica** del README generale indica anche i file di Base e HP.

## Contesto del progetto

- Il repository contiene il software del Rover: telemetria, teleoperazione, GNSS/RTK, IMU, motori, video, geofence e riproduzione supervisionata delle tracce.
- `telemetry_server.py` integra il server; `modules/` contiene la logica riutilizzabile; `static/` contiene l'interfaccia; `tests/` comprende sia test senza hardware sia programmi che azionano dispositivi fisici.
- Leggi `README.md` e i documenti pertinenti in `docs/` prima di modificare il comportamento. Distingui sempre funzionalità implementate, simulazioni, prove sul Raspberry e funzioni ancora proposte.

## Priorità e metodo di lavoro

- Dai priorità a correttezza, sicurezza delle persone e del veicolo, integrità dei dati e requisiti espliciti. Poi valuta semplicità, manutenibilità, leggibilità e prestazioni.
- Esamina codice, test, documentazione e modifiche Git già presenti prima di intervenire. Preserva il lavoro dell'utente e limita ogni modifica allo scopo richiesto.
- Preferisci la soluzione più semplice che soddisfa i requisiti. Evita funzioni ipotetiche, duplicazioni inutili e astrazioni premature. Applica KISS, YAGNI, DRY, SOLID e separazione delle responsabilità quando producono un beneficio concreto.
- Riusa le convenzioni del progetto. Mantieni espliciti i confini tra logica di controllo, accesso all'hardware, server e interfaccia web. Evita dipendenze nuove senza una necessità chiara.
- Usa nomi precisi e coerenti con il dominio. Rendi espliciti input, unità di misura, stati e condizioni di errore. Non nascondere errori né inventare valori di ripiego per dati fisici mancanti.
- Per modifiche che possono alterare il movimento, i limiti di sicurezza, la compatibilità o i dati persistenti, spiega le conseguenze e chiedi i chiarimenti indispensabili prima di procedere. Per decisioni reversibili e circoscritte, procedi autonomamente.

## Sicurezza del Rover

- Conserva un comportamento di arresto sicuro in caso di dati assenti, obsoleti o incoerenti. Non aggirare controlli su GNSS FIX, RTCM, IMU, geofence, margini di arresto, comando dell'operatore o arresto fisico per far funzionare una prova.
- L'autonomia deve restare entro un geofence locale valido e verificato. Fuori dai perimetri autorizzati è ammesso solo il comando manuale, secondo il requisito descritto in `docs/README.md`.
- Non trattare un geofence salvato nel browser come autorizzazione al movimento. Prima della trazione verifica i dati disponibili a bordo e i margini rispetto all'ingombro del veicolo, all'errore di posizione e alla distanza di arresto.
- Non presentare l'anteprima web o una simulazione come collaudo fisico. La riproduzione da terminale è sperimentale e supervisionata; consulta `docs/riproduzione-traccia.md` per stato e prerequisiti aggiornati.
- Non eseguire programmi che azionano motori, lame o altri attuatori senza una richiesta esplicita e le condizioni di sicurezza della prova. Distingui i test unitari senza hardware dagli script di prova in `tests/`.
- Non inserire credenziali o token nel repository, nel frontend, negli errori o nei log. Mantieni i controlli di autenticazione e autorizzazione esistenti.

## Verifica

- Verifica il comportamento modificato con i controlli pertinenti e disponibili. Preferisci test deterministici senza hardware per geometria, geofence, arresti e logica di controllo.
- Quando correggi un difetto, aggiungi un test di regressione se intercetta un comportamento reale e può essere eseguito in modo affidabile. Non scrivere test che ripetono soltanto l'implementazione.
- Non modificare i test solo per nascondere un errore. Non dichiarare superata una verifica che non hai eseguito. Se servono Raspberry, sensori o una prova sul campo, indica con precisione cosa resta da verificare.
- Prima di concludere, controlla che documentazione e comportamento siano coerenti e che non siano state introdotte modifiche estranee.

## Documentazione e comunicazione

- Scrivi in italiano tecnico, chiaro e naturale, salvo diversa richiesta dell'utente o convenzione locale più specifica. Mantieni i nomi di API, identificatori, protocolli, comandi e termini tecnici consolidati nella forma usata dal progetto.
- Per la documentazione applica i principi di chiarezza dell'ASD-STE100 come ispirazione stilistica indicativa, circa all'80%, senza dichiarare conformità allo standard: frasi brevi, forma attiva, terminologia costante, istruzioni operative dirette e assenza di ridondanze. Scostati da questi principi quando migliorano precisione, comprensione o naturalezza dell'italiano.
- Nei commenti e nelle docstring spiega vincoli, motivi e comportamenti non ovvi. Evita commenti che ripetono il codice. Aggiorna o rimuovi quelli divenuti inesatti.
- Documenta assunzioni, unità di misura, limiti, prerequisiti e stato delle verifiche. Se una conclusione deriva da simulazione o da documenti precedenti, dichiaralo.
- Nelle risposte distingui fatti osservati, ipotesi e proposte. Riassumi modifiche, verifiche eseguite e limiti residui in modo conciso. Non inventare risultati o capacità del sistema.

## Git e completamento

- Preserva le modifiche già presenti nel working tree. Evita riformattazioni e cambiamenti non pertinenti. Non riscrivere la cronologia Git e non eseguire commit o push senza richiesta o autorizzazione.
- Considera concluso un lavoro quando il requisito richiesto è soddisfatto, i casi di errore pertinenti sono gestiti, le verifiche possibili sono state eseguite e la documentazione interessata è aggiornata. Segnala le parti che richiedono ancora una prova fisica.
