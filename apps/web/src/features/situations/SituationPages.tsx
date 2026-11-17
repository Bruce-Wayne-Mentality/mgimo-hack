import { ArrowLeft, ArrowRight, Baby, CheckSquare, ChevronRight, FileWarning, Info, Repeat2, Shuffle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { Button, Card, CardTitle, IconChip, PageHeader } from "@/components/ui";
import { cn } from "@/lib/cn";
import { useStudy } from "../study/api";
import { NotFoundPage } from "../placeholder/pages";

// Deterministic scenarios (section 5, K9). Consequence texts are fictional demo rules.
type Option = { value: string; label: string };
type Question = { id: string; text: string; options?: Option[]; kind?: "date" | "discipline" | "number"; hint?: string };
type Outcome = { docs: string[]; consequences: string[]; request: { type: string; payload: Record<string, string | undefined> } };
type Scenario = { slug: string; title: string; lead: string; icon: typeof Baby; questions: Question[]; outcome: (answers: Record<string, string>) => Outcome };

const today = () => new Date().toISOString().slice(0, 10);

const SCENARIOS: Scenario[] = [
  {
    slug: "academic-leave",
    title: "Хочу взять академ",
    lead: "Пауза в учёбе по здоровью, семейным или иным причинам — до двух лет.",
    icon: Baby,
    questions: [
      { id: "basis", text: "По какой причине?", options: [
        { value: "medical", label: "По здоровью" }, { value: "family", label: "Семейные обстоятельства" },
        { value: "military", label: "Призыв на службу" }, { value: "other", label: "Другое" }] },
      { id: "period_from", text: "С какого числа?", kind: "date" },
      { id: "months", text: "На сколько месяцев?", options: [{ value: "6", label: "6 месяцев" }, { value: "12", label: "1 год" }, { value: "24", label: "2 года" }] },
      { id: "dorm", text: "Вы живёте в общежитии?", options: [{ value: "yes", label: "Да" }, { value: "no", label: "Нет" }] },
    ],
    outcome: (a) => ({
      docs: [
        "Заявление — сформируется в кабинете",
        a.basis === "medical" ? "Заключение врачебной комиссии" : a.basis === "military" ? "Повестка военкомата" : a.basis === "family" ? "Документ, подтверждающий обстоятельства" : "Документ, объясняющий причину",
        "Обходной лист не нужен — долги по библиотеке проверим автоматически (демо)",
      ],
      consequences: [
        "Академическая стипендия на время отпуска не выплачивается; социальная — сохраняется (демо-правило).",
        a.dorm === "yes" ? "Место в общежитии сохраняется по решению общежития; при отпуске больше года — обычно освобождается." : "Если понадобится общежитие после выхода — подайте заявку заранее.",
        "Долги текущей сессии можно закрыть после выхода из отпуска по индивидуальному графику.",
        "Выйти досрочно можно заявлением в любой момент.",
      ],
      request: { type: "ACAD_LEAVE", payload: { basis: a.basis, period_from: a.period_from, months: a.months } },
    }),
  },
  {
    slug: "transfer",
    title: "Хочу перевестись",
    lead: "Другая группа, профиль или форма обучения.",
    icon: Shuffle,
    questions: [
      { id: "target_kind", text: "Куда хотите перевестись?", options: [
        { value: "group", label: "В другую группу" }, { value: "profile", label: "На другой профиль" }, { value: "form", label: "На другую форму обучения" }] },
      { id: "target", text: "Уточните куда", options: [
        { value: "ЭК-24-2, профиль «Финансы»", label: "ЭК-24-2, «Финансы»" }, { value: "ЭК-25-2, профиль «Аналитика»", label: "ЭК-25-2, «Аналитика»" },
        { value: "Очно-заочная форма", label: "Очно-заочная форма" }] },
      { id: "debts", text: "Есть ли у вас долги по текущей сессии?", options: [{ value: "no", label: "Нет" }, { value: "yes", label: "Есть" }] },
    ],
    outcome: (a) => ({
      docs: ["Заявление — сформируется в кабинете", "Согласие принимающей кафедры — деканат запросит сам"],
      consequences: [
        a.debts === "yes" ? "С долгами перевод не оформят: сначала закройте задолженности (деканат подскажет график)." : "Перевод возможен между семестрами при наличии мест.",
        "Разницу в учебных планах закрывают по индивидуальному графику до конца следующего семестра.",
        a.target_kind === "form" ? "При переходе на очно-заочную форму меняется стоимость и стипендия (демо-правило)." : "Стипендия сохраняется, если нет долгов.",
      ],
      request: { type: "TRANSFER", payload: { target: a.target, reason: a.target_kind === "profile" ? "Хочу сменить профиль подготовки." : "Прошу рассмотреть перевод." } },
    }),
  },
  {
    slug: "failed-exam",
    title: "Не сдал экзамен",
    lead: "Что будет дальше и как записаться на пересдачу.",
    icon: Repeat2,
    questions: [
      { id: "discipline", text: "По какой дисциплине?", kind: "discipline" },
      { id: "why", text: "Что произошло?", options: [
        { value: "ill", label: "Болел, есть справка" }, { value: "failed", label: "Пришёл, но не сдал" }, { value: "missed", label: "Не пришёл без уважительной причины" }] },
      { id: "attempt", text: "Это первая пересдача?", options: [{ value: "first", label: "Первая" }, { value: "second", label: "Уже вторая" }] },
    ],
    outcome: (a) => ({
      docs: a.why === "ill" ? ["Медицинская справка — отправьте через «Вопрос в деканат»"] : ["Ничего не нужно — направление сформирует деканат"],
      consequences: [
        a.why === "ill" ? "Неявка по болезни не считается попыткой: пересдача будет первой." : "Неудачная попытка засчитывается; пересдач по одной дисциплине — не больше двух.",
        a.attempt === "second" ? "Вторая пересдача проходит перед комиссией." : "Дату пересдачи деканат назначит в течение 2 рабочих дней.",
        "Пока долг не закрыт, академическая стипендия на следующий семестр не назначается (демо-правило).",
        "Долги нужно закрыть до конца следующего семестра.",
      ],
      request: { type: "RETAKE", payload: { discipline: a.discipline, reason: a.why === "ill" ? "Болел в день экзамена, справка есть." : a.why === "missed" ? "Не явился на экзамен." : "Не сдал с первой попытки." } },
    }),
  },
];

export function SituationsPage() {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader eyebrow="Пошагово: вопросы → документы → последствия → заявка" title="Жизненные ситуации" />
      <div className="grid gap-3 md:grid-cols-3">
        {SCENARIOS.map((scenario) => (
          <Link key={scenario.slug} to={`/situations/${scenario.slug}`} className="nudge soft flex flex-col gap-3 rounded-[var(--radius-card)] bg-surface p-5 shadow-k-card hover:bg-surface-2">
            <IconChip className="size-12"><scenario.icon aria-hidden className="size-6" /></IconChip>
            <span className="text-[17px] font-medium">{scenario.title}</span>
            <span className="text-sm text-text-2">{scenario.lead}</span>
            <span className="mt-auto flex items-center gap-1 text-sm font-medium text-primary">Начать <ChevronRight aria-hidden className="size-4" /></span>
          </Link>
        ))}
      </div>
      <p className="caption m-0 flex items-center gap-1.5"><Info aria-hidden className="size-4" />Сценарии детерминированные; тексты последствий — вымышленные демо-правила.</p>
    </div>
  );
}

export function SituationPage() {
  const { slug } = useParams();
  const scenario = SCENARIOS.find((item) => item.slug === slug);
  const navigate = useNavigate();
  const study = useStudy(slug === "failed-exam");
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [step, setStep] = useState(0);
  const outcome = useMemo(() => (scenario && step >= scenario.questions.length ? scenario.outcome(answers) : null), [scenario, step, answers]);
  if (!scenario) return <NotFoundPage />;
  const question = scenario.questions[step];
  const back = <Link to="/situations" className="text-primary hover:underline">← Жизненные ситуации</Link>;

  const choose = (value: string) => {
    if (!question) return;
    setAnswers({ ...answers, [question.id]: value });
    setStep(step + 1);
  };
  const toRequest = () => {
    if (!outcome) return;
    const query = new URLSearchParams({ type: outcome.request.type });
    Object.entries(outcome.request.payload).forEach(([key, value]) => value && query.set(key, value));
    try {
      localStorage.removeItem("dekanat:request-draft");
    } catch {
      /* ignore */
    }
    navigate(`/requests/new?${query}`);
  };

  return (
    <div className="flex max-w-[720px] flex-col gap-4">
      <PageHeader eyebrow={back} title={scenario.title} />
      <ol className="m-0 flex list-none gap-1.5 p-0" aria-label="Шаги">
        {[...scenario.questions, null].map((_, index) => (
          <li key={index} className={cn("h-1.5 flex-1 rounded-full", index <= step ? "bg-primary" : "bg-line")} />
        ))}
      </ol>
      {question && (
        <Card>
          <p className="caption m-0">Вопрос {step + 1} из {scenario.questions.length}</p>
          <h2 className="m-0 mt-1 mb-4 text-[22px] font-normal tracking-[-0.02em]">{question.text}</h2>
          {question.options && (
            <div className="flex flex-col gap-2">
              {question.options.map((option) => (
                <button key={option.value} onClick={() => choose(option.value)} className={cn("nudge soft flex min-h-14 items-center justify-between rounded-[var(--radius-tile)] px-4 text-left text-[15px]", answers[question.id] === option.value ? "bg-primary-soft font-medium text-primary-strong" : "bg-surface-2 hover:bg-primary-soft")}>
                  {option.label}
                  <ArrowRight aria-hidden className="size-4 text-muted" />
                </button>
              ))}
            </div>
          )}
          {question.kind === "date" && (
            <form onSubmit={(event) => { event.preventDefault(); const value = (event.currentTarget.elements.namedItem("value") as HTMLInputElement).value; if (value) choose(value); }} className="flex gap-2">
              <input name="value" type="date" min={today()} defaultValue={answers[question.id]} required className="soft min-h-13 flex-1 rounded-[var(--radius-control)] bg-surface-2 px-4 text-base focus:shadow-[var(--k-focus-ring)] focus:outline-none" />
              <Button type="submit">Дальше</Button>
            </form>
          )}
          {question.kind === "discipline" && (
            <div className="flex flex-col gap-2">
              {(study.data?.disciplines ?? []).map((item) => (
                <button key={item.id} onClick={() => choose(item.title)} className="nudge soft flex min-h-12 items-center justify-between rounded-[var(--radius-tile)] bg-surface-2 px-4 text-left text-[15px] hover:bg-primary-soft">
                  {item.title}
                  <ArrowRight aria-hidden className="size-4 text-muted" />
                </button>
              ))}
            </div>
          )}
          {step > 0 && (
            <Button variant="ghost" className="mt-3" onClick={() => setStep(step - 1)}><ArrowLeft aria-hidden className="size-4" /> Назад</Button>
          )}
        </Card>
      )}
      {outcome && (
        <>
          <Card>
            <CardTitle meta={<CheckSquare aria-hidden className="size-5 text-primary" />}>Документы</CardTitle>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {outcome.docs.map((doc) => <li key={doc} className="flex gap-2.5 text-[15px]"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-primary" />{doc}</li>)}
            </ul>
          </Card>
          <Card className="bg-[#fffaf0]">
            <CardTitle meta={<FileWarning aria-hidden className="size-5 text-[#8a5a00]" />}>Что важно знать</CardTitle>
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {outcome.consequences.map((text) => <li key={text} className="flex gap-2.5 text-[15px]"><span aria-hidden className="mt-2 size-1.5 shrink-0 rounded-full bg-[#f5a524]" />{text}</li>)}
            </ul>
            <p className="caption m-0 mt-3">Демо-правила концепта, не нормативы реального вуза.</p>
          </Card>
          <div className="flex flex-wrap gap-2">
            <Button onClick={toRequest}>Заполнить заявку <ArrowRight aria-hidden className="size-4" /></Button>
            <Button variant="secondary" onClick={() => { setStep(0); setAnswers({}); }}>Пройти заново</Button>
            <Link to={`/assistant?q=${encodeURIComponent(scenario.title)}`} className="soft inline-flex min-h-12 items-center rounded-[var(--radius-control)] px-4 font-medium text-primary hover:bg-primary-soft">Спросить ассистента</Link>
          </div>
        </>
      )}
    </div>
  );
}
