# NEXAL Dashboard

A Next.js dashboard for monitoring your NEXAL in real-time. This dashboard connects to the same SQLite database as your Python trading bot to display signals, trades, and performance metrics.

## Features

- 📊 **Real-time Statistics**: View total signals, trades, profit/loss, and win rate
- 📈 **Performance Charts**: Visualize daily performance over the last 30 days
- 📝 **Signals Tracking**: Monitor all Telegram signals with their original messages
- 💼 **Trade Management**: View all trades including multi-TP parent-child relationships
- 🔄 **Trade Actions**: Track all modifications (SL/TP adjustments, trailing stops, etc.)
- 🎨 **Modern UI**: Built with shadcn/ui and Tailwind CSS
- 🌙 **Dark Mode Support**: Automatic dark/light theme switching

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Prerequisites

- Node.js 18+ installed
- Your trading bot database at `../prisma/dev.db`

## Installation

1. Install dependencies:

```bash
npm install
```

2. Set up Prisma:

```bash
npx prisma generate
```

3. Make sure your `.env.local` file points to the correct database:

```
DATABASE_URL="file:../prisma/dev.db"
```

## Getting Started

Run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the dashboard.

The dashboard will automatically fetch data from your trading bot's database and display:
- Overview statistics
- Performance charts
- Recent signals with their Telegram messages
- Trades with parent-child TP relationships
- Trade action history

## Database Connection

The dashboard uses Prisma to connect to the same SQLite database as your Python bot. The schema is identical but uses the Prisma Client for JavaScript instead of Python.

## Project Structure

```
dashboard/
├── src/
│   ├── app/
│   │   ├── api/          # API routes for data fetching
│   │   │   ├── signals/
│   │   │   ├── trades/
│   │   │   ├── stats/
│   │   │   └── trade-actions/
│   │   ├── globals.css   # Global styles with theme variables
│   │   └── page.tsx      # Main dashboard page
│   ├── components/
│   │   ├── ui/           # shadcn/ui components
│   │   ├── DashboardStats.tsx
│   │   ├── PerformanceChart.tsx
│   │   ├── SignalsTable.tsx
│   │   └── TradesTable.tsx
│   └── lib/
│       ├── prisma.ts     # Prisma client instance
│       └── utils.ts      # Utility functions
├── prisma/
│   └── schema.prisma     # Database schema
└── package.json
```

## API Routes

- `GET /api/stats` - Overall statistics and performance data
- `GET /api/signals?limit=50&status=EXECUTED` - Fetch signals with filters
- `GET /api/trades?limit=50&status=CLOSED` - Fetch trades with filters
- `GET /api/trade-actions?tradeId=xxx` - Fetch trade modification history

## Technologies Used

- **Next.js 14** - React framework with App Router
- **Prisma** - Database ORM
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **shadcn/ui** - UI components
- **Recharts** - Data visualization
- **Lucide React** - Icons

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load fonts.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
