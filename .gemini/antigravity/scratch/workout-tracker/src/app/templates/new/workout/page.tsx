'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft, Plus, Trash2, GripVertical, Save } from 'lucide-react';
import Link from 'next/link';
import { PageLayout } from '@/components/ui/PageLayout';
import { ExerciseSelector } from '@/components/exercises/ExerciseSelector';
import { supabase } from '@/lib/supabase';
import { DEV_USER_ID, DEFAULT_SETS, DEFAULT_REPS } from '@/lib/constants';
import type { Exercise } from '@/types';
import { cn } from '@/lib/utils';

interface TemplateItem {
    tempId: string;
    exercise: Exercise;
    sets: number;
    reps: number;
}

export default function CreateWorkoutTemplatePage() {
    const router = useRouter();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [items, setItems] = useState<TemplateItem[]>([]);
    const [showSelector, setShowSelector] = useState(false);
    const [saving, setSaving] = useState(false);

    const handleAddExercise = (exercise: Exercise) => {
        setItems(prev => [...prev, {
            tempId: Math.random().toString(36).substr(2, 9),
            exercise,
            sets: DEFAULT_SETS,
            reps: DEFAULT_REPS
        }]);
    };

    const removeItem = (index: number) => {
        setItems(prev => prev.filter((_, i) => i !== index));
    };

    const updateItem = (index: number, field: keyof TemplateItem, value: number) => {
        setItems(prev => {
            const newItems = [...prev];
            newItems[index] = { ...newItems[index], [field]: value };
            return newItems;
        });
    };

    const handleSave = async () => {
        if (!name.trim()) return;
        setSaving(true);

        try {
            // 1. Create Template
            const { data: templateData, error: templateError } = await supabase
                .from('templates')
                .insert({
                    owner_user_id: DEV_USER_ID,
                    type: 'workout',
                    name,
                    description
                })
                .select()
                .single();

            if (templateError || !templateData) throw templateError;

            // 2. Create Version 1
            const { data: versionData, error: versionError } = await supabase
                .from('template_versions')
                .insert({
                    template_id: templateData.id,
                    version_number: 1,
                    is_live: true
                })
                .select()
                .single();

            if (versionError || !versionData) throw versionError;

            // 3. Pin to Library
            await supabase.from('user_template_library').insert({
                user_id: DEV_USER_ID,
                template_id: templateData.id,
                pinned_template_version_id: versionData.id
            });

            // 4. Insert Items
            if (items.length > 0) {
                const { error: itemsError } = await supabase
                    .from('workout_template_items')
                    .insert(items.map((item, idx) => ({
                        template_version_id: versionData.id,
                        order_index: idx,
                        item_type: 'exercise',
                        exercise_id: item.exercise.id,
                        default_sets: item.sets,
                        default_reps: item.reps
                    })));

                if (itemsError) throw itemsError;
            }

            router.push('/templates');
        } catch (err) {
            console.error('Error saving template:', err);
            alert('Failed to save template. Check console.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <PageLayout
            title="Create Workout"
            action={
                <Link href="/templates/new" className="p-2 -mr-2 text-muted-foreground hover:text-foreground">
                    <ChevronLeft size={24} />
                </Link>
            }
        >
            <div className="space-y-6 pb-24">
                <div className="space-y-4">
                    <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ml-1">Name</label>
                        <input
                            type="text"
                            placeholder="e.g. Upper Power"
                            className="w-full bg-card border border-border rounded-xl px-4 py-3 mt-1 text-lg font-semibold focus:border-primary transition-colors"
                            value={name}
                            onChange={e => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ml-1">Description</label>
                        <textarea
                            placeholder="Optional notes..."
                            className="w-full bg-card border border-border rounded-xl px-4 py-3 mt-1 text-sm focus:border-primary transition-colors min-h-[80px]"
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                        />
                    </div>
                </div>

                <div className="space-y-3">
                    <div className="flex items-center justify-between">
                        <h3 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Exercises</h3>
                        <button
                            onClick={() => setShowSelector(true)}
                            className="text-primary text-sm font-semibold hover:underline flex items-center gap-1"
                        >
                            <Plus size={16} /> Add
                        </button>
                    </div>

                    <div className="space-y-3">
                        {items.map((item, index) => (
                            <div key={item.tempId} className="bg-card border border-border rounded-xl p-4 flex gap-3 animate-in fade-in slide-in-from-bottom-2 duration-300">
                                <div className="flex flex-col items-center pt-1 text-muted-foreground">
                                    <GripVertical size={20} />
                                    <span className="text-[10px] font-mono mt-1">{index + 1}</span>
                                </div>

                                <div className="flex-1 space-y-3">
                                    <div className="flex justify-between items-start">
                                        <h4 className="font-semibold">{item.exercise.name}</h4>
                                        <button onClick={() => removeItem(index)} className="text-muted-foreground hover:text-destructive transition-colors">
                                            <Trash2 size={18} />
                                        </button>
                                    </div>

                                    <div className="flex gap-4">
                                        <div className="flex-1">
                                            <label className="text-[10px] text-muted-foreground uppercase">Sets</label>
                                            <input
                                                type="number"
                                                className="w-full bg-secondary rounded-lg px-3 py-2 text-center font-medium mt-1"
                                                value={item.sets}
                                                onChange={e => updateItem(index, 'sets', parseInt(e.target.value) || 0)}
                                            />
                                        </div>
                                        <div className="flex-1">
                                            <label className="text-[10px] text-muted-foreground uppercase">Reps</label>
                                            <input
                                                type="number"
                                                className="w-full bg-secondary rounded-lg px-3 py-2 text-center font-medium mt-1"
                                                value={item.reps}
                                                onChange={e => updateItem(index, 'reps', parseInt(e.target.value) || 0)}
                                            />
                                        </div>
                                    </div>
                                </div>
                            </div>
                        ))}

                        {items.length === 0 && (
                            <div className="text-center py-8 border border-dashed border-border rounded-xl text-muted-foreground">
                                <p>No exercises added yet.</p>
                                <button
                                    onClick={() => setShowSelector(true)}
                                    className="mt-2 text-primary hover:underline font-medium"
                                >
                                    Browse Library
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                <button
                    onClick={handleSave}
                    disabled={!name.trim() || saving}
                    className={cn(
                        "fixed bottom-20 left-4 right-4 max-w-md mx-auto h-14 rounded-full font-bold text-lg shadow-lg flex items-center justify-center gap-2 transition-all",
                        !name.trim()
                            ? "bg-secondary text-muted-foreground cursor-not-allowed"
                            : "bg-primary text-primary-foreground hover:scale-[1.02] active:scale-[0.98]"
                    )}
                >
                    {saving ? 'Saving...' : <><Save size={20} /> Save Template</>}
                </button>
            </div>

            {showSelector && (
                <ExerciseSelector
                    onClose={() => setShowSelector(false)}
                    onSelect={handleAddExercise}
                    selectedIds={items.map(i => i.exercise.id)}
                />
            )}
        </PageLayout>
    );
}
