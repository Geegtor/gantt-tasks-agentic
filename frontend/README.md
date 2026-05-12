# Frontend — React + Vite + TypeScript

SPA-клиент: интерактивная диаграмма Гантта, чат-панель, модальное окно редактирования задач, импорт/экспорт Excel, тёмная тема, интернационализация.

## Содержание

1. [Локальный запуск](#локальный-запуск)
2. [Стек](#стек)
3. [Компоненты](#компоненты)
4. [Управление состоянием](#управление-состоянием)
5. [WebSocket и stale-revision guard](#websocket-и-stale-revision-guard)
6. [API-клиент](#api-клиент)
7. [Блокировка UI при чат-запросе](#блокировка-ui-при-чат-запросе)
8. [Тёмная тема](#тёмная-тема)
9. [Интернационализация](#интернационализация)
10. [Тесты](#тесты)
11. [Сборка и деплой](#сборка-и-деплой)
12. [Переменные окружения](#переменные-окружения)

---

## Локальный запуск

```bash
cd frontend
npm ci
set VITE_API_URL=http://localhost:8000    # PowerShell / CMD
npm run dev
```

Приложение: http://localhost:5173. Ожидает backend на `VITE_API_URL` (по умолч. `http://localhost:8000`).

---

## Стек

| Технология | Версия | Назначение |
|------------|--------|-----------|
| React | 18 | UI |
| TypeScript | 5.6 | Типизация |
| Vite | 5 | Сборщик + HMR |
| Zustand | 5 | Управление состоянием |
| gantt-task-react | 0.3.9 | Компонент диаграммы Гантта |
| Tailwind CSS | 3 | Стилизация (dark mode: `class` strategy) |
| Vitest + Testing Library | — | Unit-тесты |
| Playwright | — | E2E-тесты |

---

## Компоненты

### `App.tsx`

Корневой компонент. `h-screen overflow-hidden` — приложение занимает весь viewport без прокрутки страницы. Содержит:
- **Header** — логотип, кнопка «New Task», Excel Import/Export, переключатель языка, тёмная тема
- **Main** — side-by-side на ≥ lg (Gantt + Chat), stacked на mobile
- Вызывает `fetchPlan()` при монтировании
- Подключает WebSocket через `usePlanWebSocket` (exponential backoff reconnect)

### `GanttView.tsx`

| Функция | Реализация |
|---------|-----------|
| Колонки списка | Custom `TaskListTable` + `TaskListHeader` — только имя задачи |
| Hover tooltip | Custom `TooltipContent` — все поля задачи (assignee, duration, dates, predecessors, description) |
| Drag to reschedule | `onDateChange` → `PATCH /tasks/:id` с новым `start_date` |
| Double-click edit | `onDoubleClick` → открывает `TaskEditModal` |
| Dark mode | CSS `filter: invert(0.92) hue-rotate(180deg)` на `.gantt-chart-container` |
| Re-render | `key={chartKey}` (fingerprint из id:start:end) — force remount при изменении плана |
| Auto-scroll | `viewDate` = earliest task start — viewport выравнивается после обновлений |

### `ChatPanel.tsx`

- Bubble-layout: user → справа (синий), assistant → слева (серый), error → красная рамка
- Textarea с встроенной кнопкой Send (↑ arrow)
- **Enter** = отправить, **Shift+Enter** = перенос строки
- Animated typing indicator (три bouncing dots) при `chatLoading`
- Auto-scroll к последнему сообщению
- **Clarify chain** — при получении `clarify` от сервера, контекст предыдущих сообщений передаётся в следующем запросе
- **Undo** — кнопка откатывает последнюю чат-операцию (`POST /undo`)
- **Meta debug** — иконка «?» при hover показывает provenance, applied count, ops

### `TaskEditModal.tsx`

Модальное окно — открывается по клику на задачу. Режимы: редактирование / создание новой задачи.

- Поля: Name, Assignee, Description, Start date (date picker), Duration (days), Predecessors (checkbox list)
- Self-dependency предотвращена (checkbox disabled)
- Save → `PATCH /tasks/:id` / `POST /tasks` → store обновляется → chart re-renders
- Delete → `DELETE /tasks/:id`
- Блокируется при `chatLoading` с предупреждением «AI is editing the plan»

### `ExcelControls.tsx`

- Upload: `POST /upload` (multipart `.xlsx`)
- Export: прямая ссылка на `GET /export`

### `ToastContainer.tsx`

Notification toasts с auto-dismiss (4 сек). Типы: `error`, `info`.

---

## Управление состоянием

```
usePlanStore (Zustand)
├── plan: ProjectPlan | null       — текущий план
├── planRevision: number           — серверная монотонная ревизия
├── messages: ChatMessage[]        — история чата (UI)
├── chatLoading: boolean           — блокирует UI во время LLM-запроса
├── wsConnected: boolean           — статус WebSocket
├── toasts: Toast[]                — notification toasts
├── setPlan(plan, revision?)       — обновляет план с revision guard
├── addMessage(m)                  — добавляет сообщение в чат
├── setChatLoading(v)              — переключает loading state
├── addToast(message, type?)       — показывает toast (auto-dismiss 4s)
└── removeToast(id)                — убирает toast
```

Все компоненты подписываются на нужные срезы через selector: `usePlanStore(s => s.plan)` — перерендер только при изменении подписанного поля.

---

## WebSocket и stale-revision guard

`usePlanWebSocket` (хук в `App.tsx`):
1. Подключается к `getWsUrl()` (auto-derived из `VITE_API_URL` или явный `VITE_WS_URL`)
2. **Exponential backoff** — `Math.min(30000, 1000 * 2^attempt)` при disconnect
3. **Stale-revision guard** — `shouldApplyIncomingRevision(incoming, current)`:
   - Если `incoming < current` — drop (предотвращает перезапись свежего HTTP-ответа медленным WS broadcast)
   - Если `current < 0` (initial) — всегда принимаем
4. Показывает **Live / Connecting…** индикатор в ChatPanel

---

## API-клиент

`api/client.ts` — все запросы с `cache: "no-store"`.

| Функция | Метод | Эндпоинт |
|---------|-------|----------|
| `fetchPlan()` | GET | `/tasks` |
| `sendChat(message)` | POST | `/chat` |
| `uploadExcel(file)` | POST | `/upload` |
| `updateTask(id, patch)` | PATCH | `/tasks/:id` |
| `addTask(data)` | POST | `/tasks` |
| `deleteTask(id)` | DELETE | `/tasks/:id` |
| `undoChat()` | POST | `/undo` |
| `exportUrl()` | — | `/export` (прямая ссылка) |
| `getWsUrl()` | — | Auto-derive `ws://` / `wss://` из `VITE_API_URL` |

---

## Блокировка UI при чат-запросе

Когда `chatLoading=true`:
- **GanttView**: `onDateChange` возвращает `false`, контейнер затемнён (`opacity-50 pointer-events-none`)
- **TaskEditModal**: кнопки Save/Delete отключены, предупреждение «AI is editing the plan»
- **ChatPanel**: textarea и кнопка Send отключены, анимация загрузки (bouncing dots)

---

## Тёмная тема

Tailwind `darkMode: "class"`:
- `useTheme` хук: добавляет/удаляет класс `dark` на `<html>`, читает `prefers-color-scheme` при первом визите, сохраняет в `localStorage`
- Все компоненты используют `dark:` variants для фона, текста, рамок
- **Gantt chart** (third-party) — CSS filter на `.gantt-chart-container`:
  ```css
  .dark .gantt-chart-container {
    filter: invert(0.92) hue-rotate(180deg) contrast(0.95) brightness(1.05);
  }
  ```

---

## Интернационализация

`i18n/` — поддержка русского и английского через `I18nContext` (React Context).

- Язык определяется по `navigator.language` при первом визите
- Переключатель RU/EN в header
- Полная локализация: chat placeholders, gantt tooltips, modal labels, error messages
- Правильное склонение «дней» в русской версии

---

## Тесты

### Unit (Vitest)

```bash
npm test
```

12 тестов в 4 файлах: store, App (revision logic), ChatPanel, GanttView.

### E2E (Playwright)

```bash
npx playwright install chromium
npm run test:e2e
```

Сценарии: загрузка Excel → чат → экспорт. Требуется backend с `LLM_PROVIDER=mock`.

---

## Сборка и деплой

### Production build

```bash
npm run build    # tsc + vite build → dist/
```

### Vercel

- Root directory: `frontend`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variables: `VITE_API_URL`, `VITE_WS_URL` (URL backend-сервиса)

---

## Переменные окружения

| Переменная | Пример | Описание |
|------------|--------|----------|
| `VITE_API_URL` | `http://localhost:8000` | Backend base URL |
| `VITE_WS_URL` | *(опционально)* | Override WebSocket URL; auto-derived из `VITE_API_URL` если не задан |

---

## Структура проекта

```
frontend/
├── public/                    # Статические файлы (favicon, иконки)
├── src/
│   ├── main.tsx               # React root
│   ├── index.css              # Tailwind base + Gantt dark-mode CSS filter
│   ├── App.tsx                # Корневой layout, WebSocket, theme toggle
│   ├── types.ts               # ApiTask, ProjectPlan TypeScript interfaces
│   ├── hooks/
│   │   └── useTheme.ts        # Light/dark toggle + localStorage persist
│   ├── api/
│   │   └── client.ts          # HTTP/WS client (fetchPlan, sendChat, etc.)
│   ├── store/
│   │   └── usePlanStore.ts    # Zustand store
│   ├── i18n/
│   │   ├── translations.ts   # RU/EN translations
│   │   └── I18nContext.tsx    # React Context для i18n
│   └── components/
│       ├── GanttView.tsx      # Диаграмма Гантта
│       ├── ChatPanel.tsx      # Чат-панель
│       ├── TaskEditModal.tsx  # Модальное окно задачи
│       ├── ExcelControls.tsx  # Import / Export Excel
│       └── ToastContainer.tsx # Notification toasts
├── tests/                     # Vitest + Playwright
├── index.html
├── vite.config.ts
├── tailwind.config.js         # darkMode: "class"
├── tsconfig.json
└── package.json
```
