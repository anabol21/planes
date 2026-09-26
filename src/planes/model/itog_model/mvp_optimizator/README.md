# Geoscan Planner — MVP

Планировщик группового полётного задания для БВС Geoscan.

## Возможности
- Генерация полос: trapezoid или triangulation (выбор в params.json).
- Учёт препятствий (KML), рельефа (DEM из KML), GSD.
- Векторный ветер.
- Учёт времени зарядки АКБ между вылетами.
- Маршрутизация OR-Tools с ограничениями времени и энергии.
- Внешний цикл по углам θ.
- Экспорт в KML и JSON.

## Запуск
```bash
docker build -t geoscan-planner:dev .
docker run -it --rm -v ${PWD}:/app -w /app geoscan-planner:dev