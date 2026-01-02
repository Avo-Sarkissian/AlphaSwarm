-- Seed DEV user
INSERT INTO public.users (id) VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11') ON CONFLICT DO NOTHING;

-- Seed Muscles
INSERT INTO public.muscles (name) VALUES 
('Chest'), ('Back'), ('Shoulders'), ('Triceps'), ('Biceps'), 
('Quads'), ('Hamstrings'), ('Glutes'), ('Calves'), ('Abs')
ON CONFLICT (name) DO NOTHING;

-- Seed Variation Groups
INSERT INTO public.exercise_variation_groups (name) VALUES 
('Incline Press'), ('Flat Press'), ('Squat Pattern'), ('Hinge Pattern'), ('Vertical Pull'), ('Horizontal Pull')
ON CONFLICT (name) DO NOTHING;

-- Seed Exercises
-- Retrieve UUIDs for muscles and groups dynamically if this was a script, but for SQL we rely on subqueries or just inserts.
-- Check if Incline DB Press exists
INSERT INTO public.exercises (name, variation_group_id, primary_muscle_id, is_global)
VALUES 
('Incline DB Press', (SELECT id FROM public.exercise_variation_groups WHERE name='Incline Press'), (SELECT id FROM public.muscles WHERE name='Chest'), true),
('Incline Smith Press', (SELECT id FROM public.exercise_variation_groups WHERE name='Incline Press'), (SELECT id FROM public.muscles WHERE name='Chest'), true),
('Leg Press', (SELECT id FROM public.exercise_variation_groups WHERE name='Squat Pattern'), (SELECT id FROM public.muscles WHERE name='Quads'), true),
('Bulgarian Split Squat', (SELECT id FROM public.exercise_variation_groups WHERE name='Squat Pattern'), (SELECT id FROM public.muscles WHERE name='Quads'), true),
('Pull-Ups', (SELECT id FROM public.exercise_variation_groups WHERE name='Vertical Pull'), (SELECT id FROM public.muscles WHERE name='Back'), true),
('DB Shoulder Press', null, (SELECT id FROM public.muscles WHERE name='Shoulders'), true)
ON CONFLICT DO NOTHING;

-- Seed User Training State
INSERT INTO public.user_training_state (user_id, global_stage) 
VALUES ('a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11', 1)
ON CONFLICT (user_id) DO UPDATE SET global_stage = 1;

-- Seed Example Template (Upper Body)
DO $$
DECLARE
  v_user_id uuid := 'a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11';
  v_template_id uuid;
  v_version_id uuid;
  v_exercise_id uuid;
BEGIN
  -- Create Template
  INSERT INTO public.templates (owner_user_id, type, name, description)
  VALUES (v_user_id, 'workout', 'Upper Power', 'Upper body strength focus')
  RETURNING id INTO v_template_id;

  -- Create Version 1
  INSERT INTO public.template_versions (template_id, version_number, is_live)
  VALUES (v_template_id, 1, true)
  RETURNING id INTO v_version_id;

  -- Pin to library
  INSERT INTO public.user_template_library (user_id, template_id, pinned_template_version_id)
  VALUES (v_user_id, v_template_id, v_version_id);

  -- Add Exercises
  SELECT id INTO v_exercise_id FROM public.exercises WHERE name = 'Incline DB Press';
  INSERT INTO public.workout_template_items (template_version_id, order_index, item_type, exercise_id, default_sets, default_reps)
  VALUES (v_version_id, 1, 'exercise', v_exercise_id, 3, 8);

  SELECT id INTO v_exercise_id FROM public.exercises WHERE name = 'Pull-Ups';
  INSERT INTO public.workout_template_items (template_version_id, order_index, item_type, exercise_id, default_sets, default_reps)
  VALUES (v_version_id, 2, 'exercise', v_exercise_id, 3, 10);

END $$;
