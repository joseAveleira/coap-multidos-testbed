# Campaña física: captura Windows y actor Arch por SSH

Estado del 15-10-2026: campaña de cinco placas completada, con cuatro PCAP
principales de 600 s y 714030 paquetes CoAP. Las cuatro
sesiones incluyen seis episodios de cada ataque, con actor Arch separado y
las cinco identidades verificadas. Exportaciones a 0,5/1/2 s y auditorías en
`recursos/dataset_fisico/`. La C6 ejecuta MicroPython 1.29.0; las S3, Arduino.
El despliegue usa Node.js 26.10.0 ya instalado en Arch. Las pruebas previas
siguen conservadas en `test/arch_preparacion_20261014/` y el piloto anterior en
`test/capturas/fisica_4_actor_piloto_20261014_03/`.

El banco tiene cuatro ESP32-S3, un ESP32-C6, el PC servidor/capturador
y un PC Arch actor. El actor dirige los dos tipos de carga del artículo al
servidor CoAP (`/large` y `/sensor`). Las cinco placas generan tráfico legítimo.
No hay suplantación de IP, reflexión ni destinos fuera del banco privado.

## 1. Preparar el actor desde este PC

Desde la raíz del repositorio, con Python 3.13, Node 22+ y TShark/Npcap:

```powershell
python -m pip install --target .local/ssh_runtime paramiko==5.0.0
python scripts_esp32/actor/empaquetar.py
python scripts_esp32/campaign/remote.py deploy --host 10.37.225.230 --user jose --output .local/arch_deployment.json
```

Se intenta primero la autenticación configurada en SSH; si hace falta, se pide
la contraseña en terminal. También se admiten `COAP_SSH_PASSWORD` y
`COAP_SUDO_PASSWORD` solo en el entorno del proceso. No se escriben en archivos.
La primera clave del host se muestra y fija en `.local/known_hosts`; una clave
que cambie posteriormente se rechaza.

El despliegue instala únicamente paquetes base ausentes mediante sudo/pacman
(Python, curl, tar, xz), sin actualizar todo Arch. Reutiliza Node >=22 o descarga
Node 22 del sitio oficial al directorio del usuario y verifica SHA-256. Guarda
el actor en `~/coap-dataset/bundles/HASH/`, comprueba el ZIP transferido y ejecuta
las pruebas sin tráfico de red. `arch_deployment.json` recoge rutas, versiones
y resultados. Si un paso falla, no declara el despliegue completado.

Si SSH no responde, comprobar en Arch que está conectado a Aveleira, su IPv4
con `ip -4 addr` y el servicio con `sudo systemctl start sshd`. Si no está
instalado: `sudo pacman -S --needed openssh`. Actualizar host/configuración si
la IP real cambió; no deducirla de una captura anterior.

## 2. Un piloto de 180 s, con captura e inventario

Copiar `testbed.example.json` a `.local/testbed.json` y comprobar servidor,
actor e interfaz (`tshark -D`). Contiene las cinco MAC identificadas y perfiles
previstos. No reducir la lista para ocultar una placa ausente. El UDP 5683 del
PC debe estar libre: este controlador arranca y cierra su propio servidor.

```powershell
Copy-Item scripts_esp32/campaign/testbed.example.json .local/testbed.json
python scripts_esp32/campaign/capture_session.py --config .local/testbed.json --deployment .local/arch_deployment.json --plan scripts_esp32/actor/ejemplos/piloto_180s.json --session fisica_piloto_001 --output test/capturas/fisica_piloto_001
```

La carpeta y el identificador deben ser nuevos, también en Arch. El controlador:

1. Valida el plan, arranca el servidor y captura 60 s para resolver cada MAC a
   su IP observada. Si falta cualquier placa, conserva el intento y se detiene
   antes de lanzar la campaña.
2. Mide el desfase de reloj mediante siete intercambios SSH. Inicia la captura
   física, envía el plan a Arch y ejecuta el actor con sus guardas y límites.
3. Comprueba que capturador y servidor siguen activos y detecta saltos del reloj
   local. Al terminar vuelve a medir el reloj y descarga los seis registros.
4. Verifica de nuevo las identidades, guarda `dataset_manifest.json`, cierra el
   servidor y conserva diagnósticos de TShark. En errores conserva evidencias y
   marca `execution.json` como fallido; no lo convierte en una sesión válida.

No iniciar otro actor en paralelo. Para interrumpir, Ctrl+C: el controlador
solicita SIGINT al proceso remoto y STOP al servidor. Revisar `execution.json`
y los registros si hubo una parada forzada. Si se perdió SSH, comprobar también
el proceso remoto; el actor tiene un plan de duración acotada.

## 3. Convertir y revisar antes de ampliar

```powershell
python scripts_esp32/dataset/order_capture.py --capture test/capturas/fisica_piloto_001
python scripts_esp32/dataset/extract.py --manifest test/capturas/fisica_piloto_001/dataset_chronological_manifest.json --output recursos/dataset_fisico/fisica_piloto_001
python scripts_esp32/dataset/audit_capture.py --capture test/capturas/fisica_piloto_001 --export recursos/dataset_fisico/fisica_piloto_001
```

La ordenación conserva el PCAP original y verifica todos los bytes y timestamps
de los paquetes en una copia cronológica. Resuelve las inversiones de orden que
puede introducir la escritura del capturador, sin ajustar los tiempos medidos.

Revisar: cinco clientes observados, estado completado, cero pérdidas del registro
del actor, tasas solicitadas/efectivas, timeouts, huecos del planificador,
descartes TShark (desconocidos si no se informan), contadores del servidor y
ventanas excluidas. Confirmar que aparecen las tres clases a 0,5/1/2 s. Un fallo
se investiga con sus archivos; no se rellena con datos inventados.

Después del piloto se pueden generar planes más largos y variados con
`node scripts_esp32/actor_coap.js --help` y ejecutar cada sesión por
separado con el mismo controlador. Conservar cada semilla/plan, PCAP y registros.
El plan de referencia de 900 s tiene seis episodios de cada ataque; el de 180 s,
uno de cada uno. Un número equilibrado de episodios no implica igual número de
ventanas o paquetes. Publicar los recuentos observados.

## 4. Cuatro capturas de diez minutos

`capture_campaign.py` encadena sesiones, guarda su estado y se detiene ante el
primer fallo. Los planes duran 565 s; cada captura principal dura 600 s para
incluir precomprobación, espera inicial y cierre. Las cuatro suman 40 minutos.
Cada sesión tiene además 60 s de inventario y mediciones de reloj fuera de esos
40 minutos. El servidor se reinicia entre sesiones y las placas siguen activas.

```powershell
node scripts_esp32/actor_coap.js campaign --out test/planes/campana_nueva --sessions 4 --seed 2026101401 --duration 565 --pairs 6
python scripts_esp32/campaign/capture_campaign.py --config scripts_esp32/campaign/testbed.example.json --deployment .local/arch_deployment.json --campaign test/planes/campana_nueva/campaign.json --prefix fisica_5_nueva --output test/capturas/campana_nueva
```

Usar nombres y destinos nuevos. Auditar y extraer cada sesión finalizada antes
de construir un manifiesto conjunto. Una campaña interrumpida conserva las
sesiones completas anteriores y la evidencia del intento fallido.

Las instrucciones completas del operador del segundo equipo están en
[LEEME_IA.md](../actor/LEEME_IA.md). El extractor y sus reglas están documentados
en [dataset/README.md](../dataset/README.md).
