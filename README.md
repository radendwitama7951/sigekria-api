# Newspaper3k FastAPI API

A FastAPI-based API for extracting article information using Newspaper3k.

## Requirements

*   Docker
*   Docker Compose

## Running the API

1.  Clone the repository: `git clone <repository_url>`
2.  Navigate to the project directory: `cd newspaper-api`
3.  Run `docker-compose up -d`

## Endpoints

*   `/extract?url=<article_url>`: Extracts information from the provided URL.

## Database

Uses PostgreSQL for data storage.

## License

[Optional: Add a license, e.g., MIT]
