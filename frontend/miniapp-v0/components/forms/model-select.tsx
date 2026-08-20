'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Check, ChevronDown, Banana } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface Model {
  id: string
  label: string
  description: string
  cost: number
}

interface ModelSelectProps {
  models: Model[]
  value: string
  onChange: (value: string) => void
}

// Product rule: Seedance 2.5 is the only model currently highlighted as NEW.
const NEW_MODEL_IDS = new Set(['seedance_2_5'])

export function ModelSelect({ models, value, onChange }: ModelSelectProps) {
  const [isOpen, setIsOpen] = useState(false)
  const selected = models.find(m => m.id === value)
  const selectedIsNew = selected ? NEW_MODEL_IDS.has(selected.id) : false
  const orderedModels = [...models].sort(
    (left, right) => Number(NEW_MODEL_IDS.has(right.id)) - Number(NEW_MODEL_IDS.has(left.id)),
  )

  return (
    <div className="relative min-w-0">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          "w-full min-w-0 flex items-center justify-between gap-3 p-3 sm:p-4 rounded-xl",
          "bg-secondary/50 border border-border/50",
          "transition-all duration-200",
          "hover:bg-secondary hover:border-border",
          isOpen && "ring-2 ring-gold/30 border-gold/50"
        )}
      >
        <div className="min-w-0 flex-1 text-left">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium text-foreground">{selected?.label}</p>
            {selectedIsNew && (
              <span className="shrink-0 rounded-full border border-gold/60 bg-gold/25 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gold shadow-[0_0_14px_rgba(251,191,36,0.2)]">
                🔥 NEW
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground line-clamp-1">{selected?.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-gold">
            <Banana className="w-3.5 h-3.5" />
            {selected?.cost}
          </span>
          <ChevronDown className={cn(
            "w-4 h-4 text-muted-foreground transition-transform",
            isOpen && "rotate-180"
          )} />
        </div>
      </button>

      <AnimatePresence>
        {isOpen && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 z-40"
              onClick={() => setIsOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.95 }}
              transition={{ duration: 0.15 }}
              className={cn(
                "absolute z-50 mt-2 max-h-[60vh] w-full overflow-y-auto rounded-xl py-2",
                "glass-strong border border-border/50 shadow-xl"
              )}
            >
              {orderedModels.map((model) => {
                const isNew = NEW_MODEL_IDS.has(model.id)
                return (
                <button
                  key={model.id}
                  onClick={() => {
                    onChange(model.id)
                    setIsOpen(false)
                  }}
                  className={cn(
                    "w-full flex items-center gap-3 px-4 py-3",
                    "transition-colors",
                    "hover:bg-secondary/50",
                    model.id === value && "bg-gold/10",
                    isNew && "border-y border-gold/20 bg-gold/5"
                  )}
                >
                  <div className="min-w-0 flex-1 text-left">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-foreground">{model.label}</p>
                      {isNew && (
                        <span className="shrink-0 rounded-full border border-gold/60 bg-gold/25 px-2 py-0.5 text-[10px] font-bold uppercase tracking-[0.12em] text-gold shadow-[0_0_14px_rgba(251,191,36,0.2)]">
                          🔥 NEW
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground line-clamp-1">{model.description}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className="flex items-center gap-1 text-xs text-gold">
                      <Banana className="w-3.5 h-3.5" />
                      {model.cost}
                    </span>
                    {model.id === value && (
                      <Check className="w-4 h-4 text-gold" />
                    )}
                  </div>
                </button>
                )
              })}
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
