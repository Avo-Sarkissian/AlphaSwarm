-- Enable UUID extension
create extension if not exists "uuid-ossp";

-- A) USERS
create table public.users (
  id uuid primary key default uuid_generate_v4(),
  created_at timestamp with time zone default now()
);

-- B) MUSCLES / EXERCISES
create table public.muscles (
  id uuid primary key default uuid_generate_v4(),
  name text unique not null
);

create table public.exercise_variation_groups (
  id uuid primary key default uuid_generate_v4(),
  name text unique not null
);

create table public.exercises (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  variation_group_id uuid references public.exercise_variation_groups(id),
  primary_muscle_id uuid references public.muscles(id),
  created_by_user_id uuid references public.users(id),
  is_global boolean default true,
  created_at timestamp with time zone default now()
);

create table public.exercise_muscles (
  exercise_id uuid references public.exercises(id) on delete cascade,
  muscle_id uuid references public.muscles(id) on delete cascade,
  contribution text default 'secondary', -- 'primary' or 'secondary'
  primary key (exercise_id, muscle_id)
);

-- C) TEMPLATES + VERSIONING
create table public.templates (
  id uuid primary key default uuid_generate_v4(),
  owner_user_id uuid references public.users(id),
  type text not null check (type in ('workout', 'program')),
  name text not null,
  description text,
  created_at timestamp with time zone default now()
);

create table public.template_versions (
  id uuid primary key default uuid_generate_v4(),
  template_id uuid references public.templates(id) on delete cascade,
  version_number int not null,
  is_live boolean default false,
  created_at timestamp with time zone default now()
);

-- D) CONDITIONAL BLOCKS (GLOBAL STAGE)
create table public.conditional_blocks (
  id uuid primary key default uuid_generate_v4(),
  template_version_id uuid references public.template_versions(id) on delete cascade,
  name text not null,
  stage_min int not null,
  stage_max int not null
);

create table public.conditional_block_items (
  id uuid primary key default uuid_generate_v4(),
  block_id uuid references public.conditional_blocks(id) on delete cascade,
  order_index int not null,
  exercise_id uuid references public.exercises(id),
  default_sets int default 3,
  default_reps int default 8,
  rep_range_min int,
  rep_range_max int,
  notes text
);

-- E) WORKOUT TEMPLATE ITEMS
create table public.workout_template_items (
  id uuid primary key default uuid_generate_v4(),
  template_version_id uuid references public.template_versions(id) on delete cascade,
  order_index int not null,
  item_type text not null check (item_type in ('exercise', 'block_ref')),
  exercise_id uuid references public.exercises(id),
  block_id uuid references public.conditional_blocks(id), -- Only meaningful if item_type = 'block_ref'
  default_sets int default 3,
  default_reps int default 8,
  rep_range_min int,
  rep_range_max int,
  notes text
);

-- F) PROGRAM DAYS
create table public.program_days (
  id uuid primary key default uuid_generate_v4(),
  template_version_id uuid references public.template_versions(id) on delete cascade, -- must be program type
  day_index int not null, -- 1-7 (Mon-Sun or Day 1-7)
  label text not null,
  workout_template_id uuid references public.templates(id) -- link to a workout template
);

-- G) USER LIBRARY & STATE
create table public.user_template_library (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.users(id),
  template_id uuid references public.templates(id),
  pinned_template_version_id uuid references public.template_versions(id),
  added_at timestamp with time zone default now(),
  unique(user_id, template_id)
);

create table public.user_training_state (
  user_id uuid primary key references public.users(id),
  global_stage int not null default 1,
  updated_at timestamp with time zone default now()
);

-- I) WORKOUT SESSIONS
create table public.workout_sessions (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid references public.users(id),
  template_id uuid references public.templates(id),
  template_version_id uuid references public.template_versions(id),
  started_at timestamp with time zone default now(),
  ended_at timestamp with time zone,
  notes text,
  created_at timestamp with time zone default now()
);

create table public.session_exercises (
  id uuid primary key default uuid_generate_v4(),
  session_id uuid references public.workout_sessions(id) on delete cascade,
  exercise_id uuid references public.exercises(id),
  order_index int not null,
  source text not null -- 'template' | 'block' | 'manual_add'
);

create table public.session_sets (
  id uuid primary key default uuid_generate_v4(),
  session_exercise_id uuid references public.session_exercises(id) on delete cascade,
  set_index int not null,
  weight numeric not null,
  reps int not null,
  is_top_set boolean default false,
  created_at timestamp with time zone default now()
);

-- Indexes
create index idx_sessions_user_started on public.workout_sessions(user_id, started_at desc);
create index idx_session_exercises_session on public.session_exercises(session_id);
create index idx_session_sets_exercise on public.session_sets(session_exercise_id);
create index idx_exercises_variation on public.exercises(variation_group_id);
create index idx_exercise_muscles_muscle on public.exercise_muscles(muscle_id);
