# Analisi dei gap: visione, LiDAR e fusione sensori

Aggiornamento del 23 novembre 2026, dalle informazioni fornite in chat. Questo documento raccoglie requisiti e proposte: non descrive funzioni già implementate né risultati di prove sul campo.

## Configurazione riferita

- Rover con Raspberry Pi 4, GPS RTK LC29H-DA e IMU. Il LiDAR 2D COIN-D6 è circa 17 cm sopra il rover, alto 57 cm: il suo piano di scansione è quindi a circa **74 cm dal terreno**.
- Due videocamere USB Emeet sono circa 3 cm sotto il piano LiDAR, indicativamente a 71 cm da terra: una guarda avanti e una indietro. Campo visivo e inclinazione effettivi sono da misurare.
- Una terza camera CSI OV5647 è su un braccetto regolabile manualmente con viti; la posizione definitiva è ancora da scegliere.
- Gli encoder ruota sono disponibili a magazzino ma non montati. Le ruote slittano spesso sul terreno bagnato e anche fra cerchione e copertone.
- Per ora non è previsto un apparato di taglio. L'ambito iniziale della visione è diurno, con terreno visibile e persona non nascosta; erba alta, persone parzialmente nascoste e lavoro notturno non sono attualmente coperti.

## Stato e obiettivi

Il server Rover trasmette video e telemetria GPS/IMU; esistono programmi di prova separati per camere e LiDAR. La registrazione GPS avviata dall'interfaccia viene mantenuta in memoria durante la sessione e salvata all'arresto come JSON in `/home/terminator/Documents/missions/`. La guida autonoma reale, il monitor ostacoli integrato, la mappa LiDAR persistente e una protezione indipendente delle persone restano da realizzare o verificare. La geometria Pure Pursuit esiste e viene utilizzata anche in simulazione; non costituisce di per sé una guida autonoma validata sul rover.

Obiettivi richiesti: riconoscere il profilo dei filari e aiutare la centratura; riconoscere persone, comprese persone ferme e distese; mostrare riquadri e punteggi di riconoscimento in una pagina di configurazione; costruire una mappa 2D LiDAR con strutture persistenti; associare dati dei sensori e mostrare avvisi all'operatore.

## Videocamere e visione

Proposta: usare **OpenCV** per acquisizione, calibrazione, geometria e visualizzazione, insieme a un modello leggero di rilevamento come YOLO per persone e altri oggetti. Per il profilo dei filari valutare segmentazione della vegetazione o metodi geometrici. Confrontare modelli su immagini del vigneto e misurare latenza, frequenza e carico sul Pi 4 mentre streaming e altri servizi sono attivi. Verificare le condizioni di licenza del modello e del software scelti.

Un fotogramma al secondo è una frequenza iniziale per prove e visualizzazione; può introdurre fino a circa un secondo di attesa prima dell'elaborazione. A 1 m/s il rover percorre circa un metro in quel tempo, prima di aggiungere elaborazione, comando e frenata. La frequenza necessaria va stabilita dalle misure di distanza di rilevamento e arresto: 1 fps non dimostra la protezione delle persone.

Per la centratura stimare bordi sinistro e destro, centro e qualità della stima; confrontarli con traccia RTK e distanze LiDAR. Vanno gestiti ombre, controluce, foglie, pali, filari mancanti, curve, testate e perdita di uno o entrambi i bordi. Definire riduzione della velocità o arresto quando la stima è insufficiente.

La pagina proposta permette scelta della camera e delle categorie visualizzate, video con riquadri, classe e punteggio, stato e anzianità dell'ultimo frame. Il punteggio è una confidenza del modello, non una probabilità garantita. La selezione grafica non deve disattivare le funzioni necessarie alla protezione.

La OV5647 potrebbe essere provata inclinata verso il terreno davanti al rover per ridurre le zone cieche. Misurare il campo effettivamente visibile; dopo aver fissato il braccetto calibrare la camera e ripetere o verificare la calibrazione se viene spostata. Misurare anche posizione e orientamento delle Emeet rispetto al LiDAR.

### Persona distesa e limiti di copertura

Il piano LiDAR a 74 cm può passare sopra una persona distesa; anche la vista delle camere può essere ostruita. Un rilevatore generico può non riconoscere sagome distese. Occorrono immagini rappresentative, rilevamento di ostacoli bassi anche senza classificazione, studio delle zone cieche e una funzione di arresto indipendente progettata per il veicolo. Il watchdog software e i riquadri video non dimostrano la protezione. La prova della persona distesa va definita e verificata con manichini, distanze, velocità, latenze e spazio di arresto misurati.

Con erba alta o persona parzialmente nascosta, l'occlusione può impedire il riconoscimento e richiedere sensori o posizionamenti aggiuntivi. Di notte servono illuminazione adeguata o sensori idonei e prove specifiche. Questi scenari non rientrano nell'ambito iniziale e non sono dimostrati dalle prove diurne.

## LiDAR e mappa dei filari

Il COIN-D6 osserva una sezione dell'ambiente alla sua altezza, non l'intera parete dal terreno alla chioma. Le alternative proposte sono progressive:

1. **Scansioni georeferenziate:** associare scansioni a posizione e orientamento RTK/IMU e registrarle in coordinate locali; errori di posa possono sdoppiare i filari.
2. **Mappa di occupazione:** accumulare osservazioni in celle, conservando data, numero di osservazioni e incertezza. Un oggetto fermo temporaneamente non è necessariamente una parete permanente; la mappa deve poter essere aggiornata.
3. **SLAM con RTK, IMU e odometria:** confrontare scansioni successive e movimento stimato, usando RTK come riferimento quando valido. Filari ripetitivi, vegetazione mobile e qualità variabile delle misure richiedono valutazione sul campo.

Gli encoder aiuterebbero a stimare il movimento fra aggiornamenti, ma lo slittamento sul terreno e fra cerchione e copertone rende la sola rotazione delle ruote una misura incerta dello spostamento. Confrontarla con GPS, IMU e scansioni LiDAR; valutare il fissaggio meccanico degli encoder e del copertone. Una posa errata può deformare o duplicare le pareti nella mappa.

Per associare camera e LiDAR servono calibrazione interna della camera, trasformazione spaziale fra sensori, timestamp coerenti e compensazione del movimento durante la scansione. Proiettare i punti sull'immagine per verificare l'allineamento, quindi trasformarli nella mappa con la posa del rover e la relativa incertezza. La camera vede un'immagine, il LiDAR solo un piano: non ogni oggetto nell'immagine avrà punti LiDAR corrispondenti.

## Fusione e avvisi

Un supervisore a bordo dovrebbe ricevere misure, timestamp, qualità e stato di salute di camera, LiDAR, GPS, IMU e controllore. La pagina dovrebbe mostrare evento, sensore, ora e stato, distinguendo informazioni, degrado e allarmi, con storico consultabile. I dati scaduti o mancanti rappresentano uno stato sconosciuto, non strada libera.

La risposta al pericolo deve avvenire a bordo senza dipendere dalla pagina o dalla rete. Per un pericolo critico non attendere necessariamente la conferma di due sensori: definire quali rilevamenti o guasti impongono arresto, come riarmare e come verificare la funzione. La fusione software non sostituisce una protezione indipendente validata.

## Sequenza proposta e questioni aperte

1. Misurare posizione, inclinazione e campo visivo delle camere; scegliere la posizione della OV5647 e misurare velocità e arresto del rover.
2. Con rover fermo, registrare immagini e scansioni di un manichino disteso a varie distanze, individuando zone cieche e intersezione del piano LiDAR. Successivamente raccogliere dati in movimento controllato e misurare latenza e carico.
3. Sperimentare riconoscimento e pagina di configurazione, poi registrazione LiDAR georeferenziata e calibrazione camera–LiDAR.
4. Sviluppare mappa persistente, stima della corsia e supervisione inizialmente in sola osservazione; integrare successivamente il controllo.
5. Definire e validare la protezione indipendente, i casi di guasto e le prove prima dell'impiego autonomo con persone potenzialmente presenti.

Restano da definire velocità massima, dimensioni e frenata del rover, modelli e campi visivi esatti delle Emeet, geometria e inclinazione dei sensori, condizioni di prova e criteri di accettazione, sensori aggiuntivi e modalità di arresto. Nessuna delle prestazioni o coperture proposte è stata qui dimostrata.
