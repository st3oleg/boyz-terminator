# Geofencing

Cartella dei perimetri GeoJSON usati dalla pagina `riproduzione.html`. Il controllore
da terminale `modules.follow_route` legge per ora il file fisso
`GeofenceTOTALEprove.geojson` da questa cartella.

Ogni file contiene un solo poligono. La selezione nella pagina di anteprima non
cambia il file letto dal controllore. Il margine operativo va ancora validato
insieme a ingombro, precisione GNSS e distanza di arresto.
