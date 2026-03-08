import type React from "react"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"

interface ProgressCardProps {
  title: string
  value: number
  subtitle?: string
  icon?: React.ReactNode
}

export function ProgressCard({ title, value, subtitle, icon }: ProgressCardProps) {
  return (
    <Card className="glass p-6">
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            {subtitle && <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>}
          </div>
          {icon && <div className="text-accent">{icon}</div>}
        </div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-2xl font-bold gradient-text">{value}%</span>
          </div>
          <Progress value={value} className="h-2 bg-white/10" />
        </div>
      </div>
    </Card>
  )
}
