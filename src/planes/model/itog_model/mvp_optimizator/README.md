# Geoscan Planner — MVP

Планировщик группового полётного задания для БВС Geoscan.

## Запуск

docker build -t geoscan-planner:dev .
docker run -it --rm -v ${PWD}:/app -w /app geoscan-planner:dev