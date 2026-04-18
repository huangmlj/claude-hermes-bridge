import { Component, type ReactNode, type ErrorInfo } from 'react'
import { Button } from './ui/button'

interface Props {
  children: ReactNode
  fallback?: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null })
    window.location.reload()
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }
      return (
        <div className="flex flex-col items-center justify-center h-screen bg-background text-foreground p-8">
          <h1 className="text-2xl font-bold mb-4">出错了</h1>
          <p className="text-muted-foreground mb-6 text-center max-w-md">
            {this.state.error?.message || '发生了未知错误'}
          </p>
          <div className="flex gap-4">
            <Button onClick={this.handleReset}>
              重新加载
            </Button>
            <Button variant="outline" onClick={() => window.location.href = '/'}>
              返回首页
            </Button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
