"""Read-only query service adapting PostgreSQL records and Rule Registry to API schemas."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from made_core.domain.interfaces import RuleRegistry
from made_core.infrastructure.postgres.models import (
    AggregatedResultRecord,
    AlertRecord,
    DetectionResultRecord,
    ProcessedEventRecord,
)
from made_core.infrastructure.postgres.repository import PostgresStorageAdapter

from made_api.schemas.aggregates import AggregatedResultResponse
from made_api.schemas.alerts import AlertResponse
from made_api.schemas.charts import ChartHistoryResponse, ChartPoint
from made_api.schemas.common import PaginatedResponse
from made_api.schemas.detections import DetectionResultResponse
from made_api.schemas.events import ProcessedEventResponse
from made_api.schemas.metrics import MetricsResponse
from made_api.schemas.modules import ModuleConfigUpdateRequest, ModuleMetadataResponse


class MadeQueryService:
    """Service encapsulating queries and mutations against PostgreSQL and Rule Registry."""

    def __init__(
        self,
        storage: PostgresStorageAdapter,
        registry: RuleRegistry | None = None,
    ) -> None:
        self._storage = storage
        self._registry = registry

    async def check_ready(self) -> bool:
        """Probe PostgreSQL readiness."""
        return await self._storage.check_health()

    async def get_events(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        status: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> PaginatedResponse[ProcessedEventResponse]:
        """Retrieve paginated processed events."""
        records, total = await self._storage.get_processed_events(
            limit=limit,
            offset=offset,
            event_id=event_id,
            status=status,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        items = [
            ProcessedEventResponse(
                event_id=r.event_id,
                status=r.status,
                processed_at=r.processed_at,
            )
            for r in records
        ]
        return PaginatedResponse[ProcessedEventResponse](
            items=items,
            total=total,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )

    async def get_event(self, event_id: str) -> ProcessedEventResponse | None:
        """Retrieve a single processed event by event_id."""
        record = await self._storage.get_processed_event(event_id)
        if record is None:
            return None
        return ProcessedEventResponse(
            event_id=record.event_id,
            status=record.status,
            processed_at=record.processed_at,
        )

    async def get_detections(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        module_id: str | None = None,
        status: str | None = None,
        asset: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> PaginatedResponse[DetectionResultResponse]:
        """Retrieve paginated detection results."""
        records, total = await self._storage.get_detection_results(
            limit=limit,
            offset=offset,
            event_id=event_id,
            module_id=module_id,
            status=status,
            asset=asset,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        items = [
            DetectionResultResponse(
                result_id=r.result_id,
                event_id=r.event_id,
                module_id=r.module_id,
                timestamp=r.timestamp,
                asset=r.asset,
                metric_value=r.metric_value,
                threshold=r.threshold,
                anomaly_ratio=r.anomaly_ratio,
                status=r.status,
                persistence=r.persistence,
                metadata=r.metadata_json,
            )
            for r in records
        ]
        return PaginatedResponse[DetectionResultResponse](
            items=items,
            total=total,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )

    async def get_detection(self, result_id: str) -> DetectionResultResponse | None:
        """Retrieve a single detection result by result_id."""
        record = await self._storage.get_detection_result(result_id)
        if record is None:
            return None
        return DetectionResultResponse(
            result_id=record.result_id,
            event_id=record.event_id,
            module_id=record.module_id,
            timestamp=record.timestamp,
            asset=record.asset,
            metric_value=record.metric_value,
            threshold=record.threshold,
            anomaly_ratio=record.anomaly_ratio,
            status=record.status,
            persistence=record.persistence,
            metadata=record.metadata_json,
        )

    async def get_aggregates(
        self,
        limit: int = 50,
        offset: int = 0,
        asset: str | None = None,
        priority: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> PaginatedResponse[AggregatedResultResponse]:
        """Retrieve paginated aggregated results."""
        records, total = await self._storage.get_aggregated_results(
            limit=limit,
            offset=offset,
            asset=asset,
            priority=priority,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        items = [
            AggregatedResultResponse(
                aggregation_id=r.aggregation_id,
                timestamp=r.timestamp,
                asset=r.asset,
                composite_anomaly_score=r.composite_anomaly_score,
                max_anomaly_ratio=r.max_anomaly_ratio,
                average_anomaly_ratio=r.average_anomaly_ratio,
                priority=r.priority,
                module_count=r.module_count,
                triggered_modules=r.triggered_modules,
                correlation_window=r.correlation_window,
                metadata=r.metadata_json,
            )
            for r in records
        ]
        return PaginatedResponse[AggregatedResultResponse](
            items=items,
            total=total,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )

    async def get_aggregate(self, aggregation_id: str) -> AggregatedResultResponse | None:
        """Retrieve a single aggregated result by aggregation_id."""
        record = await self._storage.get_aggregated_result(aggregation_id)
        if record is None:
            return None
        return AggregatedResultResponse(
            aggregation_id=record.aggregation_id,
            timestamp=record.timestamp,
            asset=record.asset,
            composite_anomaly_score=record.composite_anomaly_score,
            max_anomaly_ratio=record.max_anomaly_ratio,
            average_anomaly_ratio=record.average_anomaly_ratio,
            priority=record.priority,
            module_count=record.module_count,
            triggered_modules=record.triggered_modules,
            correlation_window=record.correlation_window,
            metadata=record.metadata_json,
        )

    async def get_alerts(
        self,
        limit: int = 50,
        offset: int = 0,
        event_id: str | None = None,
        priority: str | None = None,
        notification_status: str | None = None,
        asset: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> PaginatedResponse[AlertResponse]:
        """Retrieve paginated alerts."""
        records, total = await self._storage.get_alerts(
            limit=limit,
            offset=offset,
            event_id=event_id,
            priority=priority,
            notification_status=notification_status,
            asset=asset,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )
        items = [
            AlertResponse(
                alert_id=r.alert_id,
                event_id=r.event_id,
                timestamp=r.timestamp,
                asset=r.asset,
                priority=r.priority,
                title=r.title,
                summary=r.summary,
                anomaly_score=r.anomaly_score,
                triggered_modules=r.triggered_modules,
                details=r.details,
                notification_status=r.notification_status,
                notification_attempts=r.notification_attempts,
                notified_at=r.notified_at,
                last_notification_error=r.last_notification_error,
                created_at=r.created_at,
            )
            for r in records
        ]
        return PaginatedResponse[AlertResponse](
            items=items,
            total=total,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
        )

    async def get_alert(self, alert_id: str) -> AlertResponse | None:
        """Retrieve a single alert by alert_id."""
        record = await self._storage.get_alert(alert_id)
        if record is None:
            return None
        return AlertResponse(
            alert_id=record.alert_id,
            event_id=record.event_id,
            timestamp=record.timestamp,
            asset=record.asset,
            priority=record.priority,
            title=record.title,
            summary=record.summary,
            anomaly_score=record.anomaly_score,
            triggered_modules=record.triggered_modules,
            details=record.details,
            notification_status=record.notification_status,
            notification_attempts=record.notification_attempts,
            notified_at=record.notified_at,
            last_notification_error=record.last_notification_error,
            created_at=record.created_at,
        )

    async def get_modules(self) -> list[ModuleMetadataResponse]:
        """Retrieve metadata and active configuration for registered detection modules."""
        module_descriptions = {
            "futures-futures-spread": "Detects anomalous price difference for the same trading pair across futures markets",
            "spot-futures-spread": "Detects anomalous price difference between spot and futures markets for the same asset",
            "dex-futures-spread": "Detects anomalous price difference between DEX and futures market data for the same asset",
            "funding-spread": "Detects anomalous funding-rate difference across futures exchanges",
        }

        # 1. Fetch DB configs if available
        db_configs = {}
        try:
            records = await self._storage.get_module_configs()
            db_configs = {r.module_id: r for r in records}
        except Exception:
            pass

        modules: list[ModuleMetadataResponse] = []
        registered_mods = self._registry.get_registered_modules() if self._registry is not None else []
        seen_ids = set()

        for module in registered_mods:
            mod_id = module.get_module_id()
            seen_ids.add(mod_id)
            desc = module_descriptions.get(mod_id, f"Detection module {mod_id}")
            cfg_rec = db_configs.get(mod_id)

            if cfg_rec is not None:
                thresh_str = f"{cfg_rec.threshold:.2f}" if mod_id != "funding-spread" else f"{cfg_rec.threshold:.4f}"
                status_str = cfg_rec.status
                ref_mode_str = cfg_rec.reference_price_mode
                max_ratio_str = f"{cfg_rec.max_price_ratio:.2f}"
                updated_at = cfg_rec.updated_at
            else:
                mod_cfg = getattr(module, "get_config", lambda: None)()
                raw_thresh = getattr(mod_cfg, "threshold", Decimal("4.0"))
                thresh_str = f"{raw_thresh:.2f}" if mod_id != "funding-spread" else f"{raw_thresh:.4f}"
                status_str = getattr(self._registry, "get_module_status", lambda _: "active")(mod_id)
                ref_mode = getattr(mod_cfg, "reference_price_mode", None)
                ref_mode_str = ref_mode.value if ref_mode is not None and hasattr(ref_mode, "value") else "AVERAGE"
                raw_ratio = getattr(mod_cfg, "max_price_ratio", Decimal("2.00"))
                max_ratio_str = f"{raw_ratio:.2f}"
                updated_at = None

            modules.append(
                ModuleMetadataResponse(
                    module_id=mod_id,
                    status=status_str,
                    description=desc,
                    threshold=thresh_str,
                    reference_price_mode=ref_mode_str,
                    max_price_ratio=max_ratio_str,
                    updated_at=updated_at,
                )
            )

        # Include any DB modules that might not be in registry instance yet
        for mod_id, cfg_rec in db_configs.items():
            if mod_id not in seen_ids:
                desc = module_descriptions.get(mod_id, f"Detection module {mod_id}")
                thresh_str = f"{cfg_rec.threshold:.2f}" if mod_id != "funding-spread" else f"{cfg_rec.threshold:.4f}"
                modules.append(
                    ModuleMetadataResponse(
                        module_id=mod_id,
                        status=cfg_rec.status,
                        description=desc,
                        threshold=thresh_str,
                        reference_price_mode=cfg_rec.reference_price_mode,
                        max_price_ratio=f"{cfg_rec.max_price_ratio:.2f}",
                        updated_at=cfg_rec.updated_at,
                    )
                )

        return modules

    async def get_module(self, module_id: str) -> ModuleMetadataResponse | None:
        """Retrieve dynamic configuration for a specific module."""
        modules = await self.get_modules()
        for mod in modules:
            if mod.module_id == module_id:
                return mod
        return None

    async def update_module_config(
        self,
        module_id: str,
        update_req: ModuleConfigUpdateRequest,
    ) -> ModuleMetadataResponse | None:
        """Persist updated module configuration to storage and update in-memory registry."""
        module_descriptions = {
            "futures-futures-spread": "Detects anomalous price difference for the same trading pair across futures markets",
            "spot-futures-spread": "Detects anomalous price difference between spot and futures markets for the same asset",
            "dex-futures-spread": "Detects anomalous price difference between DEX and futures market data for the same asset",
            "funding-spread": "Detects anomalous funding-rate difference across futures exchanges",
        }

        if self._registry is not None and not self._registry.contains(module_id) and module_id not in module_descriptions:
            return None

        # 1. Persist to PostgreSQL
        record = await self._storage.upsert_module_config(
            module_id=module_id,
            threshold=update_req.threshold,
            reference_price_mode=update_req.reference_price_mode,
            max_price_ratio=update_req.max_price_ratio,
            status=update_req.status,
        )

        # 2. Update in-memory registry and module instance if available
        if self._registry is not None and self._registry.contains(module_id):
            if update_req.status is not None:
                self._registry.set_module_status(module_id, update_req.status)
            mod = self._registry.get(module_id)
            if hasattr(mod, "update_config"):
                from made_core.domain.enums import ReferencePriceMode
                ref_mode = None
                if update_req.reference_price_mode:
                    try:
                        ref_mode = ReferencePriceMode(update_req.reference_price_mode)
                    except ValueError:
                        pass
                if module_id == "funding-spread":
                    mod.update_config(threshold=update_req.threshold)
                else:
                    mod.update_config(
                        threshold=update_req.threshold,
                        reference_price_mode=ref_mode,
                        max_price_ratio=update_req.max_price_ratio,
                    )

        desc = module_descriptions.get(module_id, f"Detection module {module_id}")
        thresh_str = f"{record.threshold:.2f}" if module_id != "funding-spread" else f"{record.threshold:.4f}"
        return ModuleMetadataResponse(
            module_id=record.module_id,
            status=record.status,
            description=desc,
            threshold=thresh_str,
            reference_price_mode=record.reference_price_mode,
            max_price_ratio=f"{record.max_price_ratio:.2f}",
            updated_at=record.updated_at,
        )

    async def get_metrics(self) -> MetricsResponse:
        """Derive operational metrics from PostgreSQL tables."""
        raw_metrics = await self._storage.get_metrics()
        return MetricsResponse(
            total_processed_events=raw_metrics["total_processed_events"],
            total_detections=raw_metrics["total_detections"],
            detections_by_status=raw_metrics["detections_by_status"],
            detections_by_module=raw_metrics["detections_by_module"],
            total_aggregates=raw_metrics["total_aggregates"],
            total_alerts=raw_metrics["total_alerts"],
            alerts_by_priority=raw_metrics["alerts_by_priority"],
            alerts_by_notification_status=raw_metrics["alerts_by_notification_status"],
        )

    async def get_chart_history(
        self,
        asset: str,
        symbol: str | None = None,
        module_id: str = "futures-futures-spread",
        timeframe: str = "1h",
    ) -> ChartHistoryResponse:
        """Derive chart timeseries points and divergence metrics for a given asset and timeframe."""
        from datetime import UTC, datetime, timedelta

        now = datetime.now(UTC)
        timeframe_map = {
            "10s": timedelta(seconds=10),
            "1m": timedelta(minutes=1),
            "15m": timedelta(minutes=15),
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
        }
        delta = timeframe_map.get(timeframe, timedelta(hours=1))
        start_time = now - delta

        records = await self._storage.get_chart_history(
            asset=asset.upper(),
            symbol=symbol.upper() if symbol else None,
            module_id=module_id,
            start_time=start_time,
            end_time=now,
            limit=2000,
        )

        resolved_symbol = symbol.upper() if symbol else f"{asset.upper()}USDT"
        points: list[ChartPoint] = []
        spread_values: list[Decimal] = []

        for rec in records:
            meta = rec.metadata_json or {}
            p1 = None
            p2 = None
            s1 = str(meta.get("firstSource") or meta.get("dexName") or meta.get("dexSource") or "Source 1")
            s2 = str(meta.get("secondSource") or meta.get("futuresSource") or "Source 2")

            if "firstPrice" in meta and meta["firstPrice"]:
                try:
                    p1 = Decimal(str(meta["firstPrice"]))
                except Exception:
                    pass
            elif "dexPrice" in meta and meta["dexPrice"]:
                try:
                    p1 = Decimal(str(meta["dexPrice"]))
                except Exception:
                    pass

            if "secondPrice" in meta and meta["secondPrice"]:
                try:
                    p2 = Decimal(str(meta["secondPrice"]))
                except Exception:
                    pass
            elif "futuresPrice" in meta and meta["futuresPrice"]:
                try:
                    p2 = Decimal(str(meta["futuresPrice"]))
                except Exception:
                    pass

            sym = str(meta.get("firstSymbol") or meta.get("spotSymbol") or meta.get("symbol") or "")
            if sym:
                resolved_symbol = sym

            is_anom = rec.status == "ANOMALY" or rec.anomaly_ratio >= Decimal("1.0")
            spread_val = rec.metric_value
            spread_values.append(spread_val)

            ts = rec.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            epoch_sec = int(ts.timestamp())

            points.append(
                ChartPoint(
                    timestamp=ts,
                    time_epoch=epoch_sec,
                    price_1=p1,
                    source_1=s1,
                    price_2=p2,
                    source_2=s2,
                    spread_percent=spread_val,
                    threshold=rec.threshold,
                    is_anomaly=is_anom,
                )
            )

        current_spread = spread_values[-1] if spread_values else None
        max_spread = max(spread_values) if spread_values else None
        avg_spread = (sum(spread_values) / len(spread_values)) if spread_values else None

        duration_seconds = 0
        if points and points[-1].is_anomaly:
            streak_start = points[-1].timestamp
            for pt in reversed(points):
                if pt.is_anomaly:
                    streak_start = pt.timestamp
                else:
                    break
            duration_seconds = max(0, int((points[-1].timestamp - streak_start).total_seconds()))

        return ChartHistoryResponse(
            asset=asset.upper(),
            symbol=resolved_symbol,
            module_id=module_id,
            timeframe=timeframe,
            points=points,
            current_spread=current_spread,
            max_spread=max_spread,
            avg_spread=avg_spread,
            spread_duration_seconds=duration_seconds,
        )
