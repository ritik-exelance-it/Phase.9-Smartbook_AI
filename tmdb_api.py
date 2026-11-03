"""Restricted, read-only TMDB API client for external movie metadata.

Only two GET endpoints are exposed: movie search and details for a numeric TMDB ID.
Cinema schedules, seat counts, ticket prices, and bookings remain SQLite-owned.
"""
from __future__ import annotations

import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

_BASE_URL = "https://api.themoviedb.org/3"
_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
_TIMEOUT = (3.05, 8.0)
_MAX_QUERY_LENGTH = 120
_MAX_RESULTS = 5
_ID_RE = re.compile(r"^[1-9]\d{0,8}$")


class TMDBError(RuntimeError):
    """Safe, user-displayable error from the TMDB integration."""


class TMDBClient:
    """Small allow-listed TMDB client. Never accepts arbitrary URLs."""

    def __init__(self, access_token: str | None = None, session=None):
        token = os.getenv("TMDB_READ_ACCESS_TOKEN", "") if access_token is None else access_token
        self._token = token.strip()
        self._session = session or requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict:
        if not self._token:
            raise TMDBError("External movie information is not configured.")
        if endpoint not in {"/search/movie", "/movie"} and not re.fullmatch(r"/movie/[1-9]\d{0,8}", endpoint):
            raise TMDBError("This movie API operation is not allowed.")

        url = _BASE_URL + endpoint
        try:
            response = self._session.get(
                url,
                params=params or {},
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Accept": "application/json",
                },
                timeout=_TIMEOUT,
            )
            if response.status_code == 404:
                raise TMDBError("No matching movie was found in the external movie database.")
            response.raise_for_status()
            payload = response.json()
        except TMDBError:
            raise
        except requests.Timeout as exc:
            raise TMDBError("The external movie service timed out. Please try again later.") from exc
        except requests.RequestException as exc:
            raise TMDBError("The external movie service is temporarily unavailable.") from exc
        except ValueError as exc:
            raise TMDBError("The external movie service returned an invalid response.") from exc

        if not isinstance(payload, dict):
            raise TMDBError("The external movie service returned an invalid response.")
        return payload

    @staticmethod
    def _clean_text(value: Any, limit: int = 1000) -> str:
        return value.strip()[:limit] if isinstance(value, str) else ""

    @classmethod
    def _normalize_movie(cls, item: dict) -> dict | None:
        movie_id = item.get("id")
        title = cls._clean_text(item.get("title"), 200)
        if not isinstance(movie_id, int) or movie_id < 1 or not title:
            return None

        poster_path = item.get("poster_path")
        backdrop_path = item.get("backdrop_path")
        release_date = cls._clean_text(item.get("release_date"), 20)
        return {
            "tmdb_id": movie_id,
            "title": title,
            "original_title": cls._clean_text(item.get("original_title"), 200),
            "overview": cls._clean_text(item.get("overview"), 1200),
            "release_date": release_date,
            "release_year": release_date[:4] if re.match(r"^\d{4}", release_date) else None,
            "original_language": cls._clean_text(item.get("original_language"), 10),
            "rating": item.get("vote_average") if isinstance(item.get("vote_average"), (int, float)) else None,
            "vote_count": item.get("vote_count") if isinstance(item.get("vote_count"), int) else None,
            "poster_url": _IMAGE_BASE_URL + poster_path if isinstance(poster_path, str) and poster_path.startswith("/") else None,
            "backdrop_url": _IMAGE_BASE_URL + backdrop_path if isinstance(backdrop_path, str) and backdrop_path.startswith("/") else None,
            "metadata_source": "TMDB",
        }

    def search_movies(self, query: str, limit: int = 5, language: str = "en-US") -> dict:
        if not isinstance(query, str):
            raise TMDBError("Enter a movie title to search.")
        query = query.strip()
        if not query or len(query) > _MAX_QUERY_LENGTH or any(ord(c) < 32 for c in query):
            raise TMDBError(f"Movie search must contain 1–{_MAX_QUERY_LENGTH} printable characters.")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= _MAX_RESULTS:
            raise TMDBError(f"Result limit must be between 1 and {_MAX_RESULTS}.")
        if language not in {"en-US", "en-GB", "hi-IN"}:
            raise TMDBError("Unsupported language setting.")

        payload = self._get("/search/movie", {
            "query": query,
            "include_adult": "false",
            "language": language,
            "page": 1,
        })
        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            raise TMDBError("The external movie service returned an invalid search response.")
        results = []
        for item in raw_results:
            if isinstance(item, dict):
                normalized = self._normalize_movie(item)
                if normalized:
                    results.append(normalized)
            if len(results) >= limit:
                break
        return {"source": "TMDB", "query": query, "count": len(results), "movies": results}

    def movie_details(self, tmdb_id: int | str, language: str = "en-US") -> dict:
        if isinstance(tmdb_id, bool) or not _ID_RE.fullmatch(str(tmdb_id).strip()):
            raise TMDBError("TMDB movie ID must be a positive integer.")
        if language not in {"en-US", "en-GB", "hi-IN"}:
            raise TMDBError("Unsupported language setting.")
        movie_id = int(tmdb_id)
        payload = self._get(
            f"/movie/{movie_id}",
            {"language": language, "append_to_response": "release_dates"},
        )
        normalized = self._normalize_movie(payload)
        if not normalized:
            raise TMDBError("The external movie service returned incomplete movie details.")
        genres = payload.get("genres", [])
        normalized["genres"] = [
            self._clean_text(item.get("name"), 80)
            for item in genres[:20]
            if isinstance(item, dict) and self._clean_text(item.get("name"), 80)
        ] if isinstance(genres, list) else []
        runtime = payload.get("runtime")
        normalized["runtime_minutes"] = (
            runtime
            if isinstance(runtime, int) and not isinstance(runtime, bool) and runtime > 0
            else None
        )
        normalized["status"] = self._clean_text(payload.get("status"), 50)
        release_dates_payload = payload.get("release_dates")
        release_dates = (
            release_dates_payload.get("results", [])
            if isinstance(release_dates_payload, dict)
            else []
        )
        certifications = []
        seen_certifications = set()
        if isinstance(release_dates, list):
            for country in release_dates:
                if not isinstance(country, dict):
                    continue
                country_code = country.get("iso_3166_1")
                entries = country.get("release_dates", [])
                if not isinstance(country_code, str) or not re.fullmatch(r"[A-Z]{2}", country_code):
                    continue
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    certification = self._clean_text(entry.get("certification"), 30)
                    key = (country_code, certification)
                    if certification and key not in seen_certifications:
                        seen_certifications.add(key)
                        certifications.append({
                            "country_code": country_code,
                            "certification": certification,
                        })
        normalized["certifications"] = certifications[:100]
        normalized["homepage"] = (
            payload.get("homepage")
            if isinstance(payload.get("homepage"), str)
            and payload["homepage"].startswith("https://")
            else None
        )
        return {"source": "TMDB", "movie": normalized}


_default_client = TMDBClient()


def search_tmdb_movies(query: str, limit: int = 5) -> dict:
    """Search external movie metadata. Never reads or writes cinema bookings."""
    return _default_client.search_movies(query, limit=limit)


def get_tmdb_movie_details(tmdb_id: int | str) -> dict:
    """Get external movie metadata by TMDB ID. Not a local cinema movie ID."""
    return _default_client.movie_details(tmdb_id)
