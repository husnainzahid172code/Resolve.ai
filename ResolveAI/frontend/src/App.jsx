import { Navigate, Route, Routes } from 'react-router-dom'
import CustomerChat from './pages/CustomerChat.jsx'
import AdminLogin from './pages/AdminLogin.jsx'
import AdminOverview from './pages/AdminOverview.jsx'
import AdminCases from './pages/AdminCases.jsx'
import AdminCaseDetail from './pages/AdminCaseDetail.jsx'
import AdminComparison from './pages/AdminComparison.jsx'
import AdminLayout from './layouts/AdminLayout.jsx'
import { useAuth } from './hooks/useAuth.js'

function Protected({ children }) {
  const { token } = useAuth()
  return token ? children : <Navigate to="/admin/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CustomerChat />} />
      <Route path="/admin/login" element={<AdminLogin />} />
      <Route path="/admin" element={<Protected><AdminLayout /></Protected>}>
        <Route index element={<AdminOverview />} />
        <Route path="cases" element={<AdminCases />} />
        <Route path="cases/:caseId" element={<AdminCaseDetail />} />
        <Route path="comparison" element={<AdminComparison />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
