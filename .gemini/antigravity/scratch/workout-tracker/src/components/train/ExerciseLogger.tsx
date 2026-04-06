'use client';

import { useState, useEffect } from 'react';
import { Plus, Minus, Check, ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import { supabase } from '@/lib/supabase';
import { useDebounce } from '@/hooks/use-debounce'; // We need this hook

interface Set {
    id: string;
    set_index: number;
    weight: number;
    reps: number;
    is_top_set: boolean;
}

interface ExerciseLoggerProps {
    sessionExerciseId: string;
    exerciseName: string;
    initialSets: Set[];
}

export function ExerciseLogger({ sessionExerciseId, exerciseName, initialSets }: ExerciseLoggerProps) {
    const [sets, setSets] = useState<Set[]>(initialSets);

    // TODO: Implement autosave with debounce
    // For v1, we will just update local state and fire-and-forget DB updates on blur/change

    const updateSet = async (setId: string, field: keyof Set, value: any) => {
        // Optimistic update
        setSets(prev => prev.map(s => s.id === setId ? { ...s, [field]: value } : s));

        // DB Update
        await supabase.from('session_sets').update({ [field]: value }).eq('id', setId);
    };

    const addSet = async () => {
        const lastSet = sets[sets.length - 1];
        const newIndex = sets.length;

        const { data } = await supabase.from('session_sets').insert({
            session_exercise_id: sessionExerciseId,
            set_index: newIndex,
            weight: lastSet ? lastSet.weight : 0,
            reps: lastSet ? lastSet.reps : 8
        }).select().single();

        if (data) {
            setSets(prev => [...prev, data]);
        }
    };

    return (
        <div className="bg-card border border-border rounded-xl overflow-hidden mb-4 scroll-mt-20">
            <div className="p-4 border-b border-border bg-card/50 flex justify-between items-center">
                <h3 className="font-bold text-lg">{exerciseName}</h3>
                <button className="text-primary text-xs font-semibold">History</button>
            </div>

            <div className="p-2 space-y-1">
                <div className="grid grid-cols-10 gap-2 mb-2 px-2 text-[10px] text-muted-foreground uppercase font-semibold text-center">
                    <div className="col-span-1">Set</div>
                    <div className="col-span-4">Weight</div>
                    <div className="col-span-4">Reps</div>
                    <div className="col-span-1"></div>
                </div>

                {sets.map((set, idx) => (
                    <div key={set.id} className={cn("grid grid-cols-10 gap-2 items-center px-2 py-1 rounded-lg transition-colors", set.is_top_set ? "bg-primary/5" : "")}>
                        <div className="col-span-1 text-center font-mono text-sm text-muted-foreground">{idx + 1}</div>

                        <div className="col-span-4">
                            <input
                                type="number"
                                className="w-full bg-secondary rounded-md py-2.5 text-center font-semibold text-lg focus:ring-1 focus:ring-primary transition-all"
                                value={set.weight || ''}
                                placeholder="0"
                                onChange={(e) => updateSet(set.id, 'weight', parseFloat(e.target.value))}
                            />
                        </div>

                        <div className="col-span-4">
                            <input
                                type="number"
                                className="w-full bg-secondary rounded-md py-2.5 text-center font-semibold text-lg focus:ring-1 focus:ring-primary transition-all"
                                value={set.reps || ''}
                                placeholder="0"
                                onChange={(e) => updateSet(set.id, 'reps', parseFloat(e.target.value))}
                            />
                        </div>

                        <div className="col-span-1 flex justify-center">
                            <button
                                onClick={() => updateSet(set.id, 'is_top_set', !set.is_top_set)}
                                className={cn("p-1.5 rounded-full", set.is_top_set ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-secondary")}
                            >
                                {set.is_top_set ? <Check size={14} /> : <Minus size={14} />}
                            </button>
                        </div>
                    </div>
                ))}

                <button
                    onClick={addSet}
                    className="w-full py-3 mt-2 flex items-center justify-center gap-2 text-sm font-semibold text-muted-foreground hover:text-primary hover:bg-secondary/50 rounded-lg transition-colors"
                >
                    <Plus size={16} /> Add Set
                </button>
            </div>
        </div>
    );
}
