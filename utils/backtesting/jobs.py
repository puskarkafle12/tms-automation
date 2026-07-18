"""Persistent PostgreSQL-backed jobs for long whole-market scans."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from utils.backtesting.batch import run_market_batch_backtest
from utils.backtesting.presets import get_backtest_presets
from utils.backtesting.service import BacktestError
from utils.technical_indicators import ENGINE_VERSION


_RUNNER_LOCK = threading.Lock()
_RUNNING_LOCAL: set[str] = set()


def _session():
    from database import SessionLocal
    return SessionLocal()


def _stored_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(parameters)
    for key in ("start_date", "end_date"):
        if isinstance(output.get(key), date):
            output[key] = output[key].isoformat()
    return output


def _runtime_parameters(parameters: Dict[str, Any]) -> Dict[str, Any]:
    output = dict(parameters)
    for key in ("start_date", "end_date"):
        if isinstance(output.get(key), str):
            output[key] = date.fromisoformat(output[key])
    return output


def _public_job(row: Dict[str, Any], *, include_result: bool = True) -> Dict[str, Any]:
    parameters = row.get("parameters") or {}
    return {
        "job_id": row["job_id"], "status": row["status"],
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at": row["finished_at"].isoformat() if row.get("finished_at") else None,
        "symbols_completed": row.get("symbols_completed") or 0,
        "symbols_total": row.get("symbols_total") or 0,
        "combinations_completed": row.get("combinations_completed") or 0,
        "current_symbol": row.get("current_symbol"),
        "percent_complete": row.get("percent_complete") or 0,
        "error": row.get("error"),
        "parameters": {
            "start_date": parameters.get("start_date"), "end_date": parameters.get("end_date"),
            "data_source": parameters.get("data_source"),
            "preset_count": len(parameters.get("preset_ids") or []) or len(get_backtest_presets()),
            "workers": parameters.get("max_workers") or 8,
            "ordinary_shares_only": parameters.get("ordinary_shares_only", True),
            "indicator_engine_version": parameters.get("indicator_engine_version"),
            "max_listing_age_days": parameters.get("max_listing_age_days"),
            "min_volume": parameters.get("min_volume"),
        },
        "has_result": row.get("result") is not None,
        "result": row.get("result") if include_result else None,
    }


def create_batch_job(parameters: Dict[str, Any]) -> Dict[str, Any]:
    job_id = uuid.uuid4().hex
    stored = _stored_parameters(parameters)
    stored.setdefault("indicator_engine_version", ENGINE_VERSION)
    session = _session()
    try:
        row = session.execute(
            text(
                """
                INSERT INTO backtest_batch_jobs (job_id, status, parameters)
                VALUES (:job_id, 'queued', CAST(:parameters AS JSONB))
                RETURNING *
                """
            ),
            {"job_id": job_id, "parameters": json.dumps(stored)},
        ).mappings().one()
        session.commit()
        return _public_job(dict(row))
    except IntegrityError as exc:
        session.rollback()
        active = session.execute(
            text("SELECT job_id FROM backtest_batch_jobs WHERE deleted_at IS NULL AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1")
        ).scalar()
        raise BacktestError(f"A market scan is already running ({active}). Open it instead of starting another.") from exc
    finally:
        session.close()


def _load_job_row(job_id: str) -> Dict[str, Any]:
    session = _session()
    try:
        row = session.execute(
            text("SELECT * FROM backtest_batch_jobs WHERE job_id = :job_id AND deleted_at IS NULL"),
            {"job_id": job_id},
        ).mappings().first()
        if not row:
            raise BacktestError("Backtest scan was not found or has been deleted.")
        return dict(row)
    finally:
        session.close()


def _load_checkpoints(job_id: str) -> List[Dict[str, Any]]:
    session = _session()
    try:
        return [dict(value) for value in session.execute(
            text("SELECT output FROM backtest_batch_job_symbols WHERE job_id = :job_id ORDER BY completed_at"),
            {"job_id": job_id},
        ).scalars().all()]
    finally:
        session.close()


def _live_rankings(job_id: str, limit: int = 30) -> List[Dict[str, Any]]:
    session = _session()
    try:
        rows = session.execute(
            text(
                """
                SELECT result
                FROM backtest_batch_job_symbols checkpoint
                CROSS JOIN LATERAL jsonb_array_elements(checkpoint.output->'results') result
                WHERE checkpoint.job_id = :job_id
                  AND COALESCE((result->>'total_trades')::INTEGER, 0) > 0
                ORDER BY (result->>'win_rate_pct')::FLOAT DESC,
                         (result->>'total_trades')::INTEGER DESC,
                         (result->>'confidence_score')::FLOAT DESC
                LIMIT :limit
                """
            ),
            {"job_id": job_id, "limit": limit},
        ).scalars().all()
        output = [dict(row) for row in rows]
        metadata = _symbol_metadata(session)
        return [{**row, **metadata.get(str(row.get("symbol")), {"security_type": "unknown", "listing_age_days": None})} for row in output]
    finally:
        session.close()


def run_batch_job(job_id: str, parameters: Optional[Dict[str, Any]] = None) -> None:
    with _RUNNER_LOCK:
        if job_id in _RUNNING_LOCAL:
            return
        _RUNNING_LOCAL.add(job_id)
    try:
        row = _load_job_row(job_id)
        if row["status"] == "completed":
            return
        runtime = _runtime_parameters(parameters or row["parameters"])
        if runtime.get("indicator_engine_version") != ENGINE_VERSION:
            session = _session()
            try:
                runtime["indicator_engine_version"] = ENGINE_VERSION
                session.execute(text("DELETE FROM backtest_batch_job_symbols WHERE job_id = :job_id"), {"job_id": job_id})
                session.execute(
                    text("UPDATE backtest_batch_jobs SET parameters = CAST(:parameters AS JSONB), symbols_completed = 0, combinations_completed = 0, percent_complete = 0 WHERE job_id = :job_id"),
                    {"job_id": job_id, "parameters": json.dumps(_stored_parameters(runtime))},
                )
                session.commit()
            finally:
                session.close()
        checkpoints = _load_checkpoints(job_id)
        session = _session()
        try:
            session.execute(
                text("UPDATE backtest_batch_jobs SET status = 'running', started_at = COALESCE(started_at, NOW()), error = NULL WHERE job_id = :job_id"),
                {"job_id": job_id},
            )
            session.commit()
        finally:
            session.close()

        def progress(completed: int, total: int, symbol: str, combinations: int, output: Optional[Dict[str, Any]]) -> None:
            session = _session()
            try:
                if output:
                    session.execute(
                        text(
                            """
                            INSERT INTO backtest_batch_job_symbols (job_id, symbol, output)
                            VALUES (:job_id, :symbol, CAST(:output AS JSONB))
                            ON CONFLICT (job_id, symbol) DO UPDATE
                            SET output = EXCLUDED.output, completed_at = NOW()
                            """
                        ),
                        {"job_id": job_id, "symbol": output["symbol"], "output": json.dumps(output)},
                    )
                    technical = output.get("technical_snapshot") or {}
                    if technical.get("indicators"):
                        from utils.market_data.repository import save_technical_indicator_snapshot
                        save_technical_indicator_snapshot(
                            session, symbol=output["symbol"],
                            as_of_date=date.fromisoformat(technical["as_of_date"]),
                            indicators=technical["indicators"], engine_version=technical["engine_version"],
                            bars_count=technical["bars_count"],
                            history_start=date.fromisoformat(technical["history_start"]),
                            history_end=date.fromisoformat(technical["history_end"]),
                        )
                session.execute(
                    text(
                        """
                        UPDATE backtest_batch_jobs
                        SET symbols_completed = :completed, symbols_total = :total,
                            combinations_completed = :combinations, current_symbol = :symbol,
                            percent_complete = :percent
                        WHERE job_id = :job_id
                        """
                    ),
                    {"job_id": job_id, "completed": completed, "total": total,
                     "combinations": combinations, "symbol": symbol or None,
                     "percent": round(completed / total * 100, 1) if total else 0},
                )
                session.commit()
            finally:
                session.close()

        try:
            result = run_market_batch_backtest(
                **runtime, progress_callback=progress,
                completed_symbol_outputs=checkpoints,
            )
        except Exception as exc:
            session = _session()
            try:
                session.execute(
                    text("UPDATE backtest_batch_jobs SET status = 'failed', error = :error, finished_at = NOW() WHERE job_id = :job_id"),
                    {"job_id": job_id, "error": str(exc)},
                )
                session.commit()
            finally:
                session.close()
            return

        session = _session()
        try:
            session.execute(
                text(
                    """
                    UPDATE backtest_batch_jobs
                    SET status = 'completed', result = CAST(:result AS JSONB),
                        symbols_completed = :symbols, symbols_total = :symbols,
                        combinations_completed = :combinations, percent_complete = 100,
                        current_symbol = NULL, finished_at = NOW()
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id, "result": json.dumps(result),
                 "symbols": result["symbols_requested"], "combinations": result["combinations_tested"]},
            )
            session.execute(text("DELETE FROM backtest_batch_job_symbols WHERE job_id = :job_id"), {"job_id": job_id})
            session.commit()
        finally:
            session.close()
    finally:
        with _RUNNER_LOCK:
            _RUNNING_LOCAL.discard(job_id)


def get_batch_job(job_id: str) -> Dict[str, Any]:
    row = _load_job_row(job_id)
    job = _public_job(row)
    if job.get("result"):
        session = _session()
        try:
            metadata = _symbol_metadata(session)
        finally:
            session.close()
        result = dict(job["result"])
        for key in ("rankings", "reliable_rankings", "stock_summary"):
            result[key] = [
                {**item, **metadata.get(str(item.get("symbol")), {"security_type": "unknown", "listing_age_days": None})}
                for item in (result.get(key) or [])
            ]
        job["result"] = result
    if row["status"] in {"queued", "running", "failed"}:
        job["live_rankings"] = _live_rankings(job_id)
    else:
        job["live_rankings"] = []
    return job


def get_batch_job_symbol(job_id: str, symbol: str) -> Dict[str, Any]:
    """Stored drill-down for one stock, valid during and after a scan."""
    row = _load_job_row(job_id)
    normalized = symbol.strip().upper()
    results: List[Dict[str, Any]] = []
    technical: Dict[str, Any] = {}
    if row.get("result"):
        results = [item for item in (row["result"].get("rankings") or []) if item.get("symbol") == normalized]
    else:
        session = _session()
        try:
            output = session.execute(
                text("SELECT output FROM backtest_batch_job_symbols WHERE job_id = :job_id AND symbol = :symbol"),
                {"job_id": job_id, "symbol": normalized},
            ).scalar() or {}
            results = list(output.get("results") or []) if isinstance(output, dict) else []
            technical = dict(output.get("technical_snapshot") or {}) if isinstance(output, dict) else {}
        finally:
            session.close()
    if not technical:
        session = _session()
        try:
            snapshot = session.execute(
                text("SELECT indicators, as_of_date, engine_version FROM market_technical_indicators WHERE symbol = :symbol"),
                {"symbol": normalized},
            ).mappings().first()
            if snapshot:
                technical = {"indicators": dict(snapshot["indicators"] or {}), "as_of_date": snapshot["as_of_date"].isoformat(), "engine_version": snapshot["engine_version"]}
        finally:
            session.close()
    results.sort(key=lambda item: (item.get("win_rate_pct") or 0, item.get("total_trades") or 0), reverse=True)
    return {"job_id": job_id, "symbol": normalized, "status": row["status"], "results": results, "technical_snapshot": technical}


def get_batch_job_rankings(job_id: str) -> List[Dict[str, Any]]:
    """Load every stored combination for safe server-side analysis."""
    row = _load_job_row(job_id)
    if row.get("result"):
        rankings = list((row["result"] or {}).get("rankings") or [])
    else:
        rankings = [item for output in _load_checkpoints(job_id) for item in output.get("results", [])]
    session = _session()
    try:
        metadata = _symbol_metadata(session)
    finally:
        session.close()
    return [{**item, **metadata.get(str(item.get("symbol")), {"security_type": "unknown", "listing_age_days": None})} for item in rankings]


def _symbol_metadata(session) -> Dict[str, Dict[str, Any]]:
    rows = session.execute(text("""
            SELECT symbol, combined_data->>'security_type' AS security_type,
                   combined_data->>'listing_age_days' AS listing_age_days,
                   combined_data
            FROM market_screener_cache
        """)).mappings().all()
    output: Dict[str, Dict[str, Any]] = {}
    for item in rows:
        try:
            age = int(float(item["listing_age_days"])) if item["listing_age_days"] not in (None, "") else None
        except (TypeError, ValueError):
            age = None
        payload = item["combined_data"] or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                payload = {}
        raw_volume = next((payload.get(key) for key in ("qty", "volume", "ml_quantity") if payload.get(key) not in (None, "")), None)
        raw_ltp = next((payload.get(key) for key in ("ltp", "ml_ltp", "close") if payload.get(key) not in (None, "")), None)
        try:
            latest_volume = float(str(raw_volume).replace(",", "")) if raw_volume is not None else None
        except (TypeError, ValueError):
            latest_volume = None
        try:
            ltp = float(str(raw_ltp).replace(",", "")) if raw_ltp is not None else None
        except (TypeError, ValueError):
            ltp = None
        sector = next((payload.get(key) for key in ("sector", "ml_sector") if payload.get(key) not in (None, "")), None)
        output[str(item["symbol"])] = {
            "security_type": str(item["security_type"] or "unknown"),
            "sector": str(sector).strip() if sector is not None else None,
            "listing_age_days": age,
            "latest_volume": latest_volume,
            "ltp": ltp,
        }
    return output


def list_batch_jobs() -> List[Dict[str, Any]]:
    session = _session()
    try:
        rows = session.execute(
            text("SELECT * FROM backtest_batch_jobs WHERE deleted_at IS NULL ORDER BY created_at DESC LIMIT 100")
        ).mappings().all()
        return [_public_job(dict(row), include_result=False) for row in rows]
    finally:
        session.close()


def delete_batch_job(job_id: str) -> None:
    session = _session()
    try:
        row = session.execute(
            text(
                """
                DELETE FROM backtest_batch_jobs
                WHERE job_id = :job_id AND status NOT IN ('queued', 'running')
                RETURNING job_id
                """
            ),
            {"job_id": job_id},
        ).scalar()
        if not row:
            session.rollback()
            existing = session.execute(text("SELECT status FROM backtest_batch_jobs WHERE job_id = :job_id"), {"job_id": job_id}).scalar()
            if existing in {"queued", "running"}:
                raise BacktestError("A running scan cannot be deleted. Let it finish first.")
            raise BacktestError("Backtest scan was not found or has already been deleted.")
        session.commit()
    finally:
        session.close()


def resume_persisted_batch_jobs() -> None:
    """Continue the one active scan from per-stock checkpoints after restart."""
    session = _session()
    try:
        job_ids = session.execute(
            text("SELECT job_id FROM backtest_batch_jobs WHERE deleted_at IS NULL AND status IN ('queued', 'running') ORDER BY created_at")
        ).scalars().all()
    finally:
        session.close()
    for job_id in job_ids:
        threading.Thread(target=run_batch_job, args=(str(job_id),), name=f"backtest-resume-{str(job_id)[:8]}", daemon=True).start()
