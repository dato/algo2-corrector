Corrector automático
====================

Este es el código fuente del corrector automático.

Consiste de:

  - El corrector automático
  - El control de copias


## Corrector automático

Corre como un servicio `corrector@algo2.service` que ejecuta _fetchmail_ para descargar el mail con la etiqueta _entregas_ de la casilla de mail. Cada mail se le envía por entrada estándar a [corrector.py](corrector.py), el cual levanta un container de Docker donde se ejecuta la corrección.

El corrector guarda entrega y resultado en el repositorio [algoritmos-rw/algo2_entregas][entregas]. Opcionalmente, si el archivo `fiubatp.tsv` está presente, se envían a repositorios individuales las entregas que pasan las pruebas.

[entregas]: https://github.com/algoritmos-rw/algo2_entregas


## Control de copias

Es un script en bash (`ojo_bionico.sh`) que invoca el script de [MOSS](https://theory.stanford.edu/~aiken/moss/): `moss.pl`.


## Instalación

  1. Instalar [Docker](https://docs.docker.com/engine/installation/).

  2. Editar el archivo netrc con la contraseña de la cuenta de correo de las
     cuales se buscan los mails, y el access token de GitHub.

  3. Ejecutar el script de instalación `install.sh`. Este programa:
      - Crea los usuarios y los grupos que se van a utilizar.
      - Compila el wrapper setgid de Docker, que permite la creación
        de containers desde una cuenta no privilegiada.
      - Instala el script principal, el servicio de systemd, y el wrapper
        compilado.
      - Baja una copia del repositorio de las entregas, que actualiza con cada
        entrega recibida.

  Todos estos parámetros son configurables desde el archivo `corrector.env`.


## Actualización de imagen de Docker

Para que los cambios realizados al worker tomen efecto, se debe actualizar la imagen local de Docker que utilizamos:

  1. Pushear al repo los cambios realizados al worker (deben estar en la rama
     master).

  2. Correr `sudo docker pull algoritmosrw/corrector` (comprobar
     antes que se actualizó la imagen de manera automática en
     [algoritmosrw/corrector](https://hub.docker.com/r/algoritmosrw/corrector).

En caso de querer recompilar la imagen manualmente:

  1. `cd repo/worker`
  2. `docker build -t algoritmosrw/corrector`
