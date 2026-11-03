"""Restricted wrappers intended for controlled agent tool routing."""
from __future__ import annotations

import re

from tmdb_api import TMDBError, search_tmdb_movies, get_tmdb_movie_details


def search_external_movie_metadata(query: str, limit: int = 5) -> dict:
    """Find external metadata for a movie title; this does not check showtimes."""
    try:
        result = search_tmdb_movies(query, limit=limit)
    except TMDBError as exc:
        return {"error": str(exc), "source": "TMDB"}
    normalized_query = re.sub(r"[^a-z0-9]+", "", query.casefold())
    exact_matches = [
        movie for movie in result["movies"]
        if re.sub(r"[^a-z0-9]+", "", movie["title"].casefold()) == normalized_query
    ]
    if len(exact_matches) == 1:
        details = get_external_movie_metadata(exact_matches[0]["tmdb_id"])
        if not details.get("error"):
            return details
        result["details_error"] = details["error"]
    return result


def get_external_movie_metadata(tmdb_id: int | str) -> dict:
    """Read TMDB metadata using a TMDB ID, not the local SQLite movie ID."""
    try:
        return get_tmdb_movie_details(tmdb_id)
    except TMDBError as exc:
        return {"error": str(exc), "source": "TMDB"}
