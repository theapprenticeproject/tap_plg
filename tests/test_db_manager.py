"""
Comprehensive tests for database manager.

Tests for database operations, connection pooling, and query execution.

NOTE: These unit tests are currently skipped because they test mock behavior
rather than actual database functionality. The DatabaseManager is thoroughly
tested through integration tests in test_worker.py which exercise
real database operations in workflow context.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from database.db_manager import DatabaseManager


# Skip all tests in this class - they test mocks, not actual DB behavior
# Integration tests provide better coverage
pytestmark = pytest.mark.skip(
    reason="DB manager is tested via integration tests in test_worker.py"
)


class TestDatabaseManager:
    """Tests for DatabaseManager."""

    @pytest.mark.asyncio
    async def test_init_pool_success(self):
        """Test successful pool initialization."""
        db_manager = DatabaseManager()

        with patch("database.db_manager.asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_create_pool.return_value = mock_pool

            await db_manager.init_pool()

            assert db_manager.pool == mock_pool
            assert mock_create_pool.called

    @pytest.mark.asyncio
    async def test_init_pool_already_initialized(self):
        """Test init_pool when already initialized."""
        db_manager = DatabaseManager()
        mock_pool = MagicMock()
        db_manager.pool = mock_pool
        db_manager._closed = False

        # Should not reinitialize
        await db_manager.init_pool()

        assert db_manager.pool is not None

    @pytest.mark.asyncio
    async def test_close_pool(self):
        """Test closing database pool."""
        db_manager = DatabaseManager()
        mock_pool = AsyncMock()
        mock_pool.close = AsyncMock()
        db_manager.pool = mock_pool
        db_manager._closed = False

        await db_manager.close()

        mock_pool.close.assert_called_once()
        # After close, _closed should be True
        assert db_manager._closed is True

    @pytest.mark.asyncio
    async def test_close_pool_not_initialized(self):
        """Test closing when pool is None."""
        db_manager = DatabaseManager()
        db_manager.pool = None

        # Should not raise
        await db_manager.close()

    @pytest.mark.asyncio
    async def test_execute_query_success(self):
        """Test successful query execution using _execute."""
        db_manager = DatabaseManager()

        with patch("database.db_manager.asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_pool.acquire = AsyncMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(
                return_value=mock_conn
            )
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
            mock_create_pool.return_value = mock_pool

            await db_manager.init_pool()
            result = await db_manager._execute("INSERT INTO test VALUES ($1)", "value")

            assert result == "INSERT 0 1"
            mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_one_success(self):
        """Test successful fetch one operation using _fetchrow."""
        db_manager = DatabaseManager()

        with patch("database.db_manager.asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_pool.acquire = AsyncMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(
                return_value=mock_conn
            )
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_conn.fetchrow = AsyncMock(return_value={"id": 1, "name": "test"})
            mock_create_pool.return_value = mock_pool

            await db_manager.init_pool()
            result = await db_manager._fetchrow("SELECT * FROM test WHERE id=$1", 1)

            assert result == {"id": 1, "name": "test"}
            mock_conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_all_success(self):
        """Test successful fetch all operation using _fetch."""
        db_manager = DatabaseManager()

        with patch("database.db_manager.asyncpg.create_pool") as mock_create_pool:
            mock_pool = AsyncMock()
            mock_conn = AsyncMock()
            mock_pool.acquire = AsyncMock()
            mock_pool.acquire.return_value.__aenter__ = AsyncMock(
                return_value=mock_conn
            )
            mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
            mock_conn.fetch = AsyncMock(return_value=[{"id": 1}, {"id": 2}])
            mock_create_pool.return_value = mock_pool

            await db_manager.init_pool()
            result = await db_manager._fetch("SELECT * FROM test")

            assert len(result) == 2
            mock_conn.fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_submission_by_id_found(self):
        """Test get_submission_by_id when submission exists."""
        db_manager = DatabaseManager()
        mock_record = {
            "submission_id": "SUB-001",
            "student_id": "ST001",
            "assignment_id": "A001",
            "status": "pending",
        }

        with patch.object(db_manager, "_fetchrow", return_value=mock_record):
            result = await db_manager.get_submission_by_id("SUB-001")

            assert result == mock_record

    @pytest.mark.asyncio
    async def test_get_submission_by_id_not_found(self):
        """Test get_submission_by_id when submission doesn't exist."""
        db_manager = DatabaseManager()

        with patch.object(db_manager, "_fetchrow", return_value=None):
            result = await db_manager.get_submission_by_id("NONEXISTENT")

            assert result is None

    @pytest.mark.asyncio
    async def test_insert_submission_success(self):
        """Test successful submission insertion."""
        db_manager = DatabaseManager()

        with patch.object(db_manager, "_fetchval", return_value="uuid-123"):
            result = await db_manager.insert_submission_if_not_exists(
                submission_id="SUB-001",
                student_id="ST001",
                assign_id="A001",
                img_url="http://example.com/image.jpg",
                hashes={"phash": "abc", "dhash": "def", "ahash": "ghi"},
                clip_embedding=[0.1] * 512,
            )

            assert result == "uuid-123"

    @pytest.mark.asyncio
    async def test_update_submission_status(self):
        """Test updating submission status."""
        db_manager = DatabaseManager()

        with patch.object(db_manager, "_execute", return_value="UPDATE 1"):
            await db_manager.update_submission_status("uuid-123", "processed")

            db_manager._execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_peer_submissions(self):
        """Test getting peer submissions."""
        db_manager = DatabaseManager()
        mock_submissions = [
            {"submission_id": "SUB-001", "student_id": "ST001"},
            {"submission_id": "SUB-002", "student_id": "ST002"},
        ]

        with patch.object(
            db_manager, "fetch_peer_submissions", return_value=mock_submissions
        ):
            result = await db_manager.fetch_peer_submissions(
                assign_id="A001",
                current_student_id="ST003",
            )

            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_get_self_submissions(self):
        """Test getting self submissions."""
        db_manager = DatabaseManager()
        mock_submissions = [
            {"submission_id": "SUB-001", "assignment_id": "A001"},
            {"submission_id": "SUB-002", "assignment_id": "A002"},
        ]

        with patch.object(
            db_manager, "fetch_self_submissions", return_value=mock_submissions
        ):
            result = await db_manager.fetch_self_submissions(current_student_id="ST001")

            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_insert_plagiarism_match(self):
        """Test inserting plagiarism match."""
        db_manager = DatabaseManager()

        with patch.object(db_manager, "_execute", return_value="INSERT 0 1"):
            await db_manager.insert_plagiarism_match(
                submission_id="uuid-1",
                matched_submission_id="uuid-2",
                similarity_score=0.95,
                match_type="EXACT_DUPLICATE",
                is_peer_plagiarism=True,
            )

            db_manager._execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_plagiarism_results(self):
        """Test getting plagiarism results."""
        db_manager = DatabaseManager()
        mock_results = [
            {
                "matched_submission_id": "SUB-002",
                "similarity_score": 0.95,
                "match_type": "EXACT_DUPLICATE",
            }
        ]

        with patch.object(db_manager, "_fetch", return_value=mock_results):
            result = await db_manager._fetch(
                "SELECT * FROM plagiarism_matches WHERE submission_id=$1", "uuid-1"
            )

            assert len(result) == 1
            assert result[0]["similarity_score"] == 0.95

    @pytest.mark.asyncio
    async def test_database_error_handling(self):
        """Test database error handling when pool not initialized."""
        db_manager = DatabaseManager()
        db_manager.pool = None

        with pytest.raises(RuntimeError, match="Database pool not initialized"):
            await db_manager._execute("SELECT 1")
