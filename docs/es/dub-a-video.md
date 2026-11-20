# Dobla un vídeo terminado

[English](../en/dub-a-video.md) · [Português](../pt/dub-a-video.md)

Parte de una entrega verificada, una pista de subtítulos en el idioma de destino y un proveedor y una voz configurados. Ejecuta estos pasos desde el repositorio de Auto-Dubbing o desde el paquete extraído.

## Previsualiza la solicitud

El ejemplo selecciona el espacio de trabajo 1, la ejecución 42 y el formato 3. Sustituye los identificadores, las rutas, el idioma y la voz por los tuyos. La vista previa indica las pistas disponibles y las solicitudes previstas para los subtítulos conocidos. No llama a ningún proveedor.

```sh
python3 tools/dub-completed-output.py /path/to/arrumo-workspaces /path/to/workspaces.sqlite 1 42 3 es elevenlabs YOUR_VOICE_ID --dry-run
```

## Renderiza y exporta

Cuando el plan esté listo, vuelve a ejecutar el comando sin la opción de vista previa. Usa all en lugar del identificador del formato para doblar todas las salidas verificadas, o añade formatos concretos con `--additional-format`. Si falta una pista traducida, puedes importarla en el vídeo terminado o usar un traductor compatible.

La herramienta adjunta cada doblaje correcto a su salida como MP4 alternativo. Abre el vídeo terminado para encontrarlo o exporta el ZIP de la entrega. Si el lote se detiene por un error, el informe indica qué formatos se completaron, fallaron o se omitieron.

Consulta [la referencia del comando](../../README.md#dub-completed-outputs) para ver las opciones de traducción, revisión, caché y renderizado aislado.
