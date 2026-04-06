'use client';

import { useState, useEffect } from 'react';
import { Search, X, Check } from 'lucide-react';
import { supabase } from '@/lib/supabase';
import type { Exercise } from '@/types';
import { cn } from '@/lib/utils';

interface ExerciseSelectorProps {
    onSelect: (exercise: Exercise) => void;
    onClose: () => void;
    selectedIds?: string[];
}

export function ExerciseSelector({ onSelect, onClose, selectedIds = [] }: ExerciseSelectorProps) {
    const [query, setQuery] = useState('');
    const [exercises, setExercises] = useState<Exercise[]>([]);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const searchExercises = async () => {
            setLoading(true);
            try {
                let dbQuery = supabase
                    .from('exercises')
                    .select('*')
                    .order('name');

                if (query.trim()) {
                    dbQuery = dbQuery.ilike('name', `%${query}%`);
                } else {
                    dbQuery = dbQuery.limit(20);
                }

                const { data, error } = await dbQuery;
                if (!error && data) {
                    setExercises(data);
                }
            } catch (err) {
                console.error(err);
            } finally {
                setLoading(false);
            }
        };

        const debounce = setTimeout(searchExercises, 300);
        return () => clearTimeout(debounce);
    }, [query]);

    return (
        <div className="fixed inset-0 z-[60] bg-background/95 backdrop-blur-sm flex flex-col animate-in fade-in duration-200">
            <div className="p-4 border-b border-border flex items-center gap-3">
                <div className="relative flex-1">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
                    <input
                        autoFocus
                        type="text"
                        placeholder="Search exercises..."
                        className="w-full bg-secondary text-foreground pl-10 pr-4 py-3 rounded-xl text-lg font-medium placeholder:text-muted-foreground/50"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </div>
                <button
                    onClick={onClose}
                    className="p-3 bg-secondary rounded-xl text-muted-foreground hover:text-foreground"
                >
                    <X size={20} />
                </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-2">
                {loading ? (
                    <div className="text-center py-10 text-muted-foreground">Searching...</div>
                ) : exercises.length === 0 ? (
                    <div className="text-center py-10 text-muted-foreground">No exercises found.</div>
                ) : (
                    exercises.map((ex) => {
                        const isSelected = selectedIds.includes(ex.id);
                        return (
                            <button
                                key={ex.id}
                                onClick={() => {
                                    onSelect(ex);
                                    onClose();
                                }}
                                disabled={isSelected}
                                className={cn(
                                    "w-full text-left p-4 rounded-xl flex items-center justify-between border transition-all",
                                    isSelected
                                        ? "bg-secondary/50 border-transparent opacity-50 cursor-default"
                                        : "bg-card border-border hover:border-primary/50 active:scale-[0.99]"
                                )}
                            >
                                <div>
                                    <h4 className="font-semibold text-foreground">{ex.name}</h4>
                                    <p className="text-xs text-muted-foreground">Muscle Group</p>
                                </div>
                                {isSelected && <Check size={18} className="text-primary" />}
                            </button>
                        );
                    })
                )}
            </div>
        </div>
    );
}
