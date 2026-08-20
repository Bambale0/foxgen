'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Check, ChevronDown, Coins } from 'lucide-react'
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
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'fox-surface flex w-full min-w-0 items-center justify-between gap-3 rounded-xl p-3 text-left sm:p-4',
          'transition-all duration-200 hover:border-gold/25 hover:bg-secondary/70',
          isOpen && 'border-gold/45 ring-2 ring-gold/15',
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-foreground">{selected?.label}</p>
            {selectedIsNew && (
              <span className="shrink-0 rounded-full border border-gold/45 bg-gold/[0.12] px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.12em] text-gold shadow-[0_0_14px_rgba(255,106,0,0.12)]">
                NEW
              </span>
            )}
          </div>
          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{selected?.description}</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="flex items-center gap-1 text-xs font-bold text-gold">
            <Coins className="h-3.5 w-3.5" />
            {selected?.cost}
          </span>
          <ChevronDown className={cn(
            'h-4 w-4 text-muted-foreground transition-transform',
            isOpen && 'rotate-180 text-gold',
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
              initial={{ opacity: 0, y: -8, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.97 }}
              transition={{ duration: 0.15 }}
              className={cn(
                'glass-strong absolute z-50 mt-2 max-h-[60vh] w-full overflow-y-auto rounded-2xl border border-white/[0.08] py-2 shadow-[0_24px_64px_rgba(0,0,0,0.55)]',
              )}
            >
              {orderedModels.map((model) => {
                const isNew = NEW_MODEL_IDS.has(model.id)
                return (
                  <button
                    key={model.id}
                    type="button"
                    onClick={() => {
                      onChange(model.id)
                      setIsOpen(false)
                    }}
                    className={cn(
                      'flex w-full items-center gap-3 px-4 py-3 transition-colors hover:bg-gold/[0.05]',
                      model.id === value && 'bg-gold/[0.08]',
                    )}
                  >
                    <div className="min-w-0 flex-1 text-left">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-sm font-semibold text-foreground">{model.label}</p>
                        {isNew && (
                          <span className="shrink-0 rounded-full border border-gold/45 bg-gold/[0.12] px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.12em] text-gold">
                            NEW
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{model.description}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="flex items-center gap-1 text-xs font-bold text-gold">
                        <Coins className="h-3.5 w-3.5" />
                        {model.cost}
                      </span>
                      {model.id === value && (
                        <Check className="h-4 w-4 text-gold" />
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
