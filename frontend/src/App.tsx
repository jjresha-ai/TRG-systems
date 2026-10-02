import { Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout'
import Login from '@/pages/Login'
import Home from '@/pages/Home'
import ComingSoon from '@/pages/ComingSoon'
import Contacts from '@/pages/Contacts'
import ContactDetail from '@/pages/ContactDetail'
import Companies from '@/pages/Companies'
import CompanyDetail from '@/pages/CompanyDetail'
import Properties from '@/pages/Properties'
import PropertyDetail from '@/pages/PropertyDetail'
import Duplicates from '@/pages/Duplicates'
import Prospecting from '@/pages/Prospecting'
import Deals from '@/pages/Deals'
import DealDetail from '@/pages/DealDetail'
import Tasks from '@/pages/Tasks'
import Listings from '@/pages/Listings'
import ListingDetail from '@/pages/ListingDetail'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/contacts" element={<Contacts />} />
        <Route path="/contacts/:id" element={<ContactDetail />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/companies/:id" element={<CompanyDetail />} />
        <Route path="/properties" element={<Properties />} />
        <Route path="/properties/:id" element={<PropertyDetail />} />
        <Route path="/prospecting" element={<Prospecting />} />
        <Route path="/deals" element={<Deals />} />
        <Route path="/deals/:id" element={<DealDetail />} />
        <Route path="/tasks" element={<Tasks />} />
        <Route path="/listings" element={<Listings />} />
        <Route path="/listings/:id" element={<ListingDetail />} />
        <Route path="/duplicates" element={<Duplicates />} />
        <Route path="*" element={<ComingSoon />} />
      </Route>
    </Routes>
  )
}
