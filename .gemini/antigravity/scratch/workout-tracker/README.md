# Mobile-First Workout Tracker

A premium, offline-capable mobile web app for tracking workouts with gym-first UI, template versioning, and advanced progression metrics.

## Features

- **Train**: Start session from pinned templates, live logging with large touch targets, autosave.
- **Templates**: Create workout templates with versioning support (Editing = New Version).
- **Progress**: Dashboard with volume/PR trends, E1RM analysis graphs per exercise.
- **Premium UI**: Dark mode optimization, Recharts visualization, Lucide icons.

## Tech Stack

- **Frontend**: Next.js 15 (App Router), TypeScript, Tailwind CSS v4.
- **Backend**: Supabase (Postgres).
- **State**: React Server Components + Client Hooks.

## Getting Started

1. **Install Dependencies**
   ```bash
   npm install
   ```

2. **Supabase Setup**
   - Create a new Supabase project.
   - Run the SQL in `supabase/schema.sql` in the Supabase SQL Editor.
   - Run the Seed in `supabase/seed.sql` to populate initial muscles/exercises and the Dev User.
   - Get your Project URL and Anon Key from Project Settings > API.

3. **Environment Variables**
   Create a `.env.local` file in the root:
   ```env
   NEXT_PUBLIC_SUPABASE_URL=your_project_url
   NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
   ```

4. **Run Locally**
   ```bash
   npm run dev
   ```
   Open [http://localhost:3000](http://localhost:3000).

## Dev User Mode
The app is currently in **Single User Dev Mode**.
- `DEV_USER_ID` is hardcoded in `src/lib/constants.ts` (`a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11`).
- All queries are scoped to this ID.
- The Seed script creates this user in the `users` table.

## Deployment (Vercel)
1. Push to GitHub.
2. Import project in Vercel.
3. Add `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` to Vercel Environment Variables.
4. Deploy.
