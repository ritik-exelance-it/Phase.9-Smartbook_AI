import unittest
from unittest.mock import Mock, patch

import requests

import agent
import tmdb_tools
from tmdb_api import TMDBClient, TMDBError


def response(payload, status=200):
    result = Mock()
    result.status_code = status
    result.json.return_value = payload
    result.raise_for_status.return_value = None
    return result


class TMDBClientTests(unittest.TestCase):
    def setUp(self):
        self.session = Mock()
        self.client = TMDBClient("test-token", session=self.session)

    def test_search_uses_only_fixed_search_endpoint_and_bearer_auth(self):
        self.session.get.return_value = response({
            "results": [{
                "id": 11, "title": "Example", "overview": "A film",
                "release_date": "2024-01-02", "poster_path": "/poster.jpg",
                "vote_average": 7.5, "vote_count": 22,
            }]
        })
        result = self.client.search_movies("Example")
        self.assertEqual(result["movies"][0]["tmdb_id"], 11)
        self.assertEqual(result["movies"][0]["poster_url"], "https://image.tmdb.org/t/p/w500/poster.jpg")
        args, kwargs = self.session.get.call_args
        self.assertEqual(args[0], "https://api.themoviedb.org/3/search/movie")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertEqual(kwargs["timeout"], (3.05, 8.0))

    def test_search_rejects_empty_or_oversized_query_without_network(self):
        with self.assertRaises(TMDBError):
            self.client.search_movies("  ")
        with self.assertRaises(TMDBError):
            self.client.search_movies("x" * 121)
        self.session.get.assert_not_called()

    def test_search_limit_is_bounded(self):
        with self.assertRaises(TMDBError):
            self.client.search_movies("Example", limit=100)
        self.session.get.assert_not_called()

    def test_details_requires_positive_numeric_tmdb_id(self):
        for bad_id in ("https://evil.example", "../11", "0", "-1", "1/credits", True):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(TMDBError):
                    self.client.movie_details(bad_id)
        self.session.get.assert_not_called()

    def test_details_uses_fixed_id_endpoint_and_normalizes_genres(self):
        self.session.get.return_value = response({
            "id": 42, "title": "Sample", "genres": [{"name": "Drama"}],
            "runtime": 120, "homepage": "https://example.com",
            "release_dates": {"results": [
                {"iso_3166_1": "US", "release_dates": [
                    {"certification": "PG-13"},
                    {"certification": "PG-13"},
                    {"certification": ""},
                ]},
                {"iso_3166_1": "IN", "release_dates": [
                    {"certification": "UA"},
                ]},
            ]},
        })
        result = self.client.movie_details(42)
        self.assertEqual(result["movie"]["tmdb_id"], 42)
        self.assertEqual(result["movie"]["genres"], ["Drama"])
        self.assertEqual(result["movie"]["runtime_minutes"], 120)
        self.assertEqual(result["movie"]["certifications"], [
            {"country_code": "US", "certification": "PG-13"},
            {"country_code": "IN", "certification": "UA"},
        ])
        self.assertEqual(self.session.get.call_args.args[0], "https://api.themoviedb.org/3/movie/42")
        self.assertEqual(
            self.session.get.call_args.kwargs["params"]["append_to_response"],
            "release_dates",
        )

    def test_unconfigured_client_fails_closed(self):
        with self.assertRaises(TMDBError):
            TMDBClient("", session=self.session).search_movies("Sample")
        self.session.get.assert_not_called()

    def test_external_movie_details_requires_tmdb_id(self):
        state: agent.AgentState = {
            "intent": "external_movie_details",
            "tmdb_id": None,
        }
        with patch("agent.get_external_movie_metadata") as get_details:
            result = agent.execute_node(state)

        get_details.assert_not_called()
        self.assertEqual(
            result["result_data"]["error"],
            "A TMDB movie ID is required for external movie details.",
        )

    def test_timeout_has_safe_error(self):
        self.session.get.side_effect = requests.Timeout()
        with self.assertRaisesRegex(TMDBError, "timed out"):
            self.client.search_movies("Sample")


class TMDBToolTests(unittest.TestCase):
    def test_exact_search_match_is_enriched_with_certifications(self):
        search_result = {
            "source": "TMDB",
            "query": "The Devil's Mouth",
            "count": 1,
            "movies": [{
                "tmdb_id": 88,
                "title": "The Devil's Mouth",
                "release_year": "2024",
            }],
        }
        details = {
            "source": "TMDB",
            "movie": {
                "tmdb_id": 88,
                "title": "The Devil's Mouth",
                "certifications": [{"country_code": "IN", "certification": "UA"}],
            },
        }
        with patch.object(tmdb_tools, "search_tmdb_movies", return_value=search_result), patch.object(
            tmdb_tools, "get_external_movie_metadata", return_value=details
        ) as get_details:
            result = tmdb_tools.search_external_movie_metadata("The Devil's Mouth")

        get_details.assert_called_once_with(88)
        self.assertEqual(result, details)

    def test_agent_caches_external_movie_facts_for_followup_questions(self):
        movie = {
            "title": "The Devil's Mouth",
            "overview": "A verified synopsis.",
            "certifications": [{"country_code": "IN", "certification": "UA"}],
        }
        with patch(
            "agent.search_external_movie_metadata",
            return_value={"source": "TMDB", "movie": movie},
        ):
            result = agent.execute_node({
                "intent": "external_movie_search",
                "movie_title": "The Devil's Mouth",
            })

        self.assertEqual(result["active_movie_metadata"], movie)
        self.assertEqual(result["active_movie_title"], "The Devil's Mouth")


if __name__ == "__main__":
    unittest.main()
