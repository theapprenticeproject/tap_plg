



# Copilot Custom Instruction: MentorMe Plagiarism System

## Step-by-Step Agent Workflow
1. **Identify what you want to change:**
   - Is it a message format, hash/embedding logic, DB schema, or a new detection method?
2. **Locate the right file(s):**
   - See the file map below for entrypoints and handlers.
3. **Check contracts before editing:**
   - See “Core Contracts” below. If your change affects a contract, update all consumers.
4. **Make your change.**
5. **Add or update tests:**
   - For new features, add a minimal test in `tests/simulation_e2e.py` or a new file in `tests/`.
6. **Run e2e simulation and sanity checks.**
7. **Review the PR checklist before submitting.**

## Core Contracts (Must Not Break)
**MQ message format:**
  - Submissions/feedback are JSON dicts. Required keys: `submission_id`, `student_id`, `assign_id`, `img_url`.
  - Example:
    ```json
    {
      "submission_id": "SUB-001",
      "student_id": "ST001",
      "assign_id": "A001",
      "img_url": "https://..."
    }
    ```
**Hash dict contract:**
  - Always a dict with keys: `phash`, `dhash`, `ahash` (see `hash_handler.py`).
  - Example:
    ```python
    {"phash": "abcd1234...", "dhash": "efgh5678...", "ahash": "ijkl9012..."}
    ```
**CLIP embedding contract:**
  - 512-D numpy array, normalized (unit vector). Similarity = dot-product (cosine).
  - Example:
    ```python
    embedding = clip_handler.generate_embedding(image)  # shape (512,)
    assert np.isclose(np.linalg.norm(embedding), 1.0)
    ```
**DB schema contract:**
  - Any schema change must update all SQL in `db_manager.py` and consumers. Grep for `INSERT INTO submissions` and `UPDATE submissions`.

## Anti-Patterns (Never Do This)
1. **Never change `prefetch_count` in MQ** without updating ack/retry logic in both `mq/rmq_client.py` and `plag_checker/submissions_checker.py`.
2. **Never change hash dict keys or CLIP normalization logic** without updating all consumers.
3. **Never update DB schema** without updating all SQL and consumers.
4. **Never skip `initialize()` or `close()`** for async resources (DB, MQ, vector backend).

## File Map for Common Agent Tasks
- **Add new detection method:** Start in `image_worker/worker.py`, add handler in `image_worker/`.
- **Change message format:** Update `mq/rmq_client.py` and all consumers.
- **Change DB schema:** Update `database/init.sql`, `database/db_manager.py`, and all SQL queries.
- **Add vector backend:** Implement in `image_worker/faiss_handler.py` or `image_worker/pgvector_handler.py`, update selection logic in `worker.py`.
- **Add test:** Use `tests/simulation_e2e.py` for e2e, or add new file in `tests/`.

## Error Handling & Debugging
1. **If RabbitMQ/DB fails:** Restart containers and check logs (`podman logs ...`).
2. **If CLIP/FAISS fails:** Check model download and index path.
3. **For async bugs:** Verify all awaits and shutdown paths.
4. **For contract errors:** Grep for all usages and update them (see “Core Contracts”).

## Extending the System
1. **When adding a new handler:** Follow the single-responsibility pattern (see existing handlers).
2. **Always update contracts and tests** for new/changed logic.
3. **If adding a new vector backend:** Ensure all embedding logic supports both FAISS and pgvector.

## PR Checklist (For Copilot Agents)
1. Run e2e simulation
2. Check for new/changed async code
3. Validate `.env` and config contracts
4. Update tests for any handler/contract change

## If Stuck or Unsure
1. Ask maintainers about:
   - Intended production vector backend (FAISS vs pgvector)
   - Acceptable changes to prefetch/parallelism

---
For more examples, see referenced files and test scripts. Request expansion or more examples if needed.
