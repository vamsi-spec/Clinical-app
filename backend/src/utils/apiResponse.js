export const successResponse = (res, data = null, message = 'Success', statusCode = 200) => {
    return res.status(statusCode).json({
        success: true,
        message,
        data,
    })
}

export const errorResponse = (res, message = 'Internal server error', statusCode = 500, error = null) => {
    const response = {
        success: false,
        message,
    }

    if (process.env.NODE_ENV === 'development' && error) {
        response.error = error instanceof Error ? error.message : error
        response.stack = error instanceof Error ? error.stack : undefined
    }

    return res.status(statusCode).json(response)
}

export const paginatedResponse = (res, data, pagination, message = 'Success') => {
    return res.status(200).json({
        success: true,
        message,
        data,
        pagination: {
            page: pagination.page,
            limit: pagination.limit,
            total: pagination.total,
            totalPages: Math.ceil(pagination.total / pagination.limit),
            hasNext: pagination.page < Math.ceil(pagination.total / pagination.limit),
            hasPrev: pagination.page > 1,
        },
    })
}


export const validationErrorResponse = (res, errors) => {
    return res.status(422).json({
        success: false,
        message: 'Validation failed',
        errors,
    })
}


