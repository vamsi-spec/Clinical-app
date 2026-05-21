export default function App() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 p-6">
      <div className="max-w-md w-full bg-white rounded-2xl shadow-xl overflow-hidden ring-1 ring-gray-900/5">
        <div className="p-8">
          <div className="flex items-center justify-center w-16 h-16 bg-primary-100 rounded-full mb-6">
            <svg
              className="w-8 h-8 text-primary-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="2"
                d="M13 10V3L4 14h7v7l9-11h-7z"
              ></path>
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">
            Tailwind CSS v4
          </h1>
          <p className="text-gray-500 mb-6 leading-relaxed">
            Your React frontend is now beautifully styled with the lightning-fast Tailwind CSS v4 engine. Ready for development!
          </p>
          <div className="space-y-3">
            <button className="w-full py-3 px-4 bg-primary-600 hover:bg-primary-700 text-white font-medium rounded-xl transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2">
              Get Started
            </button>
            <button className="w-full py-3 px-4 bg-gray-50 hover:bg-gray-100 text-gray-700 font-medium rounded-xl border border-gray-200 transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-gray-200 focus:ring-offset-2">
              View Documentation
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
