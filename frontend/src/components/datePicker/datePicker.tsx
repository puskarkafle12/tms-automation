import React from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';

interface DatePickerComponentProps {
  orderedDate: Date | null;
  setOrderedDate: (date: Date | null) => void;
}

const DatePickerComponent: React.FC<DatePickerComponentProps> = ({ orderedDate, setOrderedDate }) => {
  const handleDateChange = (date: Date | null) => {
    setOrderedDate(date);
  };

  return (
    <label>
      Ordered Date:
      <DatePicker
        selected={orderedDate}
        onChange={handleDateChange}
        dateFormat="yyyy-MM-dd"
        placeholderText="Select a date"
      />
    </label>
  );
};

export default DatePickerComponent;
