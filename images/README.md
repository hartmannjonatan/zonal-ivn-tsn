# Recursos visuais

`background/car.png` e `misc/camera.png` são cópias sem alteração dos arquivos
homônimos de `inet-4.7.0/images/`. O fundo é o mesmo usado pelo showcase
`showcases/tsn/combiningfeatures/invehicle/InVehicleNetworkShowcase.ned`.
A licença distribuída pelo INET está preservada em `INET-LICENSE.md`.

`simulations/omnetpp.ini` inclui esta pasta via `image-path = ../images`, para
que o fundo e a câmera não dependam do caminho absoluto da instalação do INET.
Os demais ícones (`device/*` e `block/*`) pertencem à biblioteca padrão do
OMNeT++. O scanner representa visualmente o LiDAR e a antena direcional o radar;
os rótulos LIDAR/RADAR explicitam as funções, sem modelar o hardware dos sensores.
