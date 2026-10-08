import type { QualityStatus, Workload } from "../../shared/api/types";

export const WORKLOAD_LABELS: Record<Workload, string> = {
  normal: "Обычное",
  increased: "Повышенное",
  excluded: "Не учитывать в наградах",
};

export const QUALITY_LABELS: Record<QualityStatus, string> = {
  pending: "Ждёт проверки взрослым",
  confirmed: "Взрослый подтвердил",
  rejected: "Нужно доработать",
  not_required: "—",
};

export const SOURCE_LABELS = { timer: "Таймер", manual: "Вручную" } as const;
